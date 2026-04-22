"""
This module provides an MCP (Model Context Protocol) server for the opp_repl Python library.

The server runs on a background thread and exposes a single ``execute_python`` tool that
executes arbitrary Python code in the live IPython session. The AI assistant shares the
same namespace as the interactive user, so all opp_repl functions (run_simulations,
compare_simulations, run_fingerprint_tests, etc.) are available directly.
"""

import ctypes
import inspect
import io
import logging
import os
import pydoc
import re
import signal
import sys
import threading
import traceback

try:
    from mcp.server.fastmcp import FastMCP
    _mcp_available = True
except ImportError:
    _mcp_available = False

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

mcp_calls = []

_active_mcp_thread_id = None
_original_sigint_handler = None

def _sigint_handler(signum, frame):
    tid = _active_mcp_thread_id
    if tid is not None:
        _logger.info("Ctrl-C: interrupting MCP execution")
        ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(tid),
            ctypes.py_object(KeyboardInterrupt)
        )
    elif _original_sigint_handler is not None:
        _original_sigint_handler(signum, frame)
    else:
        raise KeyboardInterrupt

def _strip_ansi(text):
    return re.sub(r"\033\[[0-9;]*m", "", str(text))

if _mcp_available:
    _mcp = FastMCP("opp_repl", host="127.0.0.1", port=9966, stateless_http=True)

def _get_subpackages(root_package):
    """Return a sorted list of all sub-packages under root_package (filesystem-based, no imports)."""
    import os
    root_dir = root_package.__path__[0]
    prefix = root_package.__name__
    packages = [prefix]
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("_") and not d.startswith("."))
        for d in dirnames:
            if os.path.isfile(os.path.join(dirpath, d, "__init__.py")):
                relpath = os.path.relpath(os.path.join(dirpath, d), root_dir)
                pkg_name = prefix + "." + relpath.replace(os.sep, ".")
                packages.append(pkg_name)
    return sorted(packages)

def _register_mcp_handlers():
    @_mcp.resource("file:///opp_repl/packages")
    def package_list() -> str:
        """List all opp_repl sub-packages with their docstrings."""
        import opp_repl
        lines = []
        for pkg_name in _get_subpackages(opp_repl):
            mod = sys.modules.get(pkg_name)
            if mod is None:
                first_line = "(not loaded)"
            else:
                doc = inspect.getdoc(mod) or ""
                first_line = doc.split("\n")[0] if doc else "(no description)"
            lines.append(f"{pkg_name}\n    {first_line}")
        return "\n\n".join(lines)

    @_mcp.resource("file:///opp_repl/readme")
    def readme() -> str:
        """The opp_repl README with installation instructions, usage examples, and feature overview."""
        readme_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "README.md")
        with open(readme_path, "r") as f:
            return f.read()

    @_mcp.resource("file:///opp_repl/api/{package_name}")
    def api_reference(package_name: str) -> str:
        """Public API reference for a specific opp_repl package, auto-generated from docstrings."""
        mod = sys.modules.get(package_name)
        if mod is None:
            return f"Package '{package_name}' not loaded."
        all_names = getattr(mod, "__all__", None)
        if all_names is None:
            all_names = [n for n in dir(mod) if not n.startswith("_")]
        lines = []
        module_doc = inspect.getdoc(mod)
        if module_doc:
            lines.append(module_doc)
        for name in sorted(all_names):
            obj = getattr(mod, name, None)
            if obj is None:
                continue
            obj_mod = getattr(obj, "__module__", None) or ""
            if not obj_mod.startswith("opp_repl"):
                continue
            if inspect.isfunction(obj):
                doc = inspect.getdoc(obj) or ""
                if not doc:
                    continue
                try:
                    sig = str(inspect.signature(obj))
                except (ValueError, TypeError):
                    sig = "(...)"
                indented = "\n".join("    " + l for l in doc.split("\n"))
                lines.append(f"{name}{sig}\n{indented}")
            elif inspect.isclass(obj):
                doc = inspect.getdoc(obj) or ""
                if not doc:
                    continue
                indented = "\n".join("    " + l for l in doc.split("\n"))
                cls_lines = [f"class {name}\n{indented}"]
                for mname, mobj in inspect.getmembers(obj, predicate=inspect.isfunction):
                    if mname.startswith("_"):
                        continue
                    mmod = getattr(mobj, "__module__", None) or ""
                    if not mmod.startswith("opp_repl"):
                        continue
                    mdoc = inspect.getdoc(mobj) or ""
                    if not mdoc:
                        continue
                    try:
                        msig = str(inspect.signature(mobj))
                    except (ValueError, TypeError):
                        msig = "(...)"
                    mindented = "\n".join("        " + l for l in mdoc.split("\n"))
                    cls_lines.append(f"    {mname}{msig}\n{mindented}")
                lines.append("\n\n".join(cls_lines))
        return "\n\n".join(lines) if lines else f"No documented public API in '{package_name}'."

    @_mcp.tool()
    def execute_python(code: str) -> str:
        """Execute Python code in the live IPython session.

        The code runs in the same namespace as the interactive REPL user.
        All public opp_repl packages, functions and classes are pre-loaded.

        IMPORTANT: Before writing any code, always read the API resources first.
        Do NOT guess function names, parameter names, or signatures. Look them up.
        Do NOT import packages that are already pre-loaded.

        To discover the API:
        - Read file:///opp_repl/readme for the project README with usage examples
        - Read file:///opp_repl/packages for a list of sub-packages
        - Read file:///opp_repl/api/{package_name} for the API of a specific package
        - Call help(function_name) to get detailed documentation

        Args:
            code: Python code to execute.

        Returns:
            Captured stdout/stderr output. If the code is a single expression,
            its repr is returned.
        """
        import IPython
        ip = IPython.get_ipython()
        _logger.info(f"execute_python:\n{code}")
        mcp_calls.append({"tool": "execute_python", "code": code})

        if ip is not None:
            # Run in the live IPython session — shared namespace with the user
            global _active_mcp_thread_id
            _active_mcp_thread_id = threading.get_ident()

            # Disable interactive pager so help() prints text directly
            old_pager = pydoc.pager
            pydoc.pager = pydoc.plainpager

            # Capture stdout so the AI sees printed output
            captured = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                result = ip.run_cell(code, silent=False, store_history=False)
            except KeyboardInterrupt:
                text = "Interrupted by user (Ctrl-C)"
                _logger.info(text)
                return text
            finally:
                sys.stdout = old_stdout
                pydoc.pager = old_pager
                _active_mcp_thread_id = None

            # Capture the cell output
            parts = []
            output = captured.getvalue()
            if output:
                parts.append(_strip_ansi(output.rstrip()))
            if result.result is not None:
                parts.append(_strip_ansi(repr(result.result)))
            if result.error_in_exec is not None:
                parts.append(_strip_ansi(str(result.error_in_exec)))
            if result.error_before_exec is not None:
                parts.append(_strip_ansi(str(result.error_before_exec)))
            text = "\n".join(parts) if parts else "(no output)"
        else:
            # Fallback: no IPython session (e.g. testing outside the REPL)
            namespace = {"__builtins__": __builtins__}
            exec("from opp_repl import *", namespace)
            stdout = io.StringIO()
            stderr = io.StringIO()
            try:
                import contextlib
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    try:
                        result = eval(code, namespace)
                        if result is not None:
                            print(repr(result))
                    except SyntaxError:
                        exec(code, namespace)
            except Exception:
                stderr.write(traceback.format_exc())
            output = stdout.getvalue()
            errors = stderr.getvalue()
            text = (output + ("\n--- STDERR ---\n" + errors if errors else "")).strip()
            if not text:
                text = "(no output)"

        _logger.info(f"execute_python → {text}")
        return _strip_ansi(text)

if _mcp_available:
    _register_mcp_handlers()

def start_mcp_server(port=9966):
    """Start the MCP server on a background thread using Streamable HTTP transport.

    The server uses stateless HTTP mode so each tool call is an independent
    HTTP POST request. This makes server restarts transparent to clients —
    no persistent connection needs to be re-established.

    Endpoint: http://127.0.0.1:{port}/mcp

    Args:
        port: The port to listen on (default 9966).
    """
    if not _mcp_available:
        raise ImportError("MCP server requires the 'mcp' package. Install it with: pip install opp_repl[mcp]")

    global _original_sigint_handler
    _original_sigint_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _sigint_handler)

    _mcp.settings.port = port
    _mcp.settings.log_level = "WARNING"
    logging.getLogger("mcp").setLevel(logging.WARNING)

    def _run():
        try:
            _mcp.run(transport="streamable-http")
        except Exception as e:
            _logger.error(f"MCP server failed: {e}")

    thread = threading.Thread(target=_run, daemon=True, name="opp-repl-mcp-server")
    thread.start()
    _logger.info(f"MCP server started on port {port}")
    return thread
