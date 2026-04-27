"""
This module provides an MCP (Model Context Protocol) server for the opp_repl Python library.

The server runs on a background thread and exposes a single ``execute_python`` tool that
executes arbitrary Python code in the live IPython session. The AI assistant shares the
same namespace as the interactive user, so all opp_repl functions (run_simulations,
compare_simulations, run_fingerprint_tests, etc.) are available directly.
"""

import ctypes
import glob
import inspect
import io
import logging
import os
from pathlib import Path
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
    _mcp = FastMCP("opp_repl", host="127.0.0.1", port=9966, stateless_http=True,
                    instructions="""\
Recommended discovery flow:
1. Read opp-repl://guides to find the relevant guide topic
2. Read opp-repl://guide/{topic} for usage examples
3. Read opp-repl://packages to find the relevant sub-package
4. Read opp-repl://package/{package_name} for a compact API overview
5. Drill into opp-repl://class/…, opp-repl://method/…, or opp-repl://function/… for full details

Do NOT search in files, do NOT read files, do NOT run shell commands unless you
checked that there is no explicit opp_repl support for the given functionality.""")

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

def _resolve_opp_repl_name(name, kind=None):
    """Resolve *name* to a Python object by searching loaded opp_repl modules.

    *name* may be fully qualified (e.g. ``opp_repl.simulation.workspace.SimulationWorkspace``)
    or a short public name (e.g. ``SimulationWorkspace``).

    *kind* may be ``"class"``, ``"function"``, or ``None`` (any).

    Returns ``(obj, qualified_name)`` or ``(None, None)``.
    """
    # 1. Try direct attribute lookup for a fully-qualified name
    parts = name.rsplit(".", 1)
    if len(parts) == 2:
        mod = sys.modules.get(parts[0])
        if mod is not None:
            obj = getattr(mod, parts[1], None)
            if obj is not None:
                if kind == "class" and not inspect.isclass(obj):
                    return None, None
                if kind == "function" and not inspect.isfunction(obj):
                    return None, None
                return obj, name

    # 2. Search all loaded opp_repl modules for a short name
    for mod_name, mod in sorted(sys.modules.items()):
        if mod is None or not mod_name.startswith("opp_repl"):
            continue
        obj = getattr(mod, name, None)
        if obj is None:
            continue
        obj_mod = getattr(obj, "__module__", None) or ""
        if not obj_mod.startswith("opp_repl"):
            continue
        if kind == "class" and not inspect.isclass(obj):
            continue
        if kind == "function" and not inspect.isfunction(obj):
            continue
        qualified = f"{obj_mod}.{obj.__qualname__}"
        return obj, qualified
    return None, None

def _register_mcp_handlers():
    @_mcp.resource("opp-repl://packages")
    def package_list() -> str:
        """List all opp_repl sub-packages with their docstrings."""
        import opp_repl
        lines = []
        for pkg_name in _get_subpackages(opp_repl):
            mod = sys.modules.get(pkg_name)
            if mod is None:
                summary = "(not loaded)"
            else:
                doc = inspect.getdoc(mod) or ""
                if doc:
                    summary = doc.split("\n\n")[0].replace("\n", " ")
                else:
                    summary = "(no description)"
            lines.append(f"{pkg_name}\n    {summary}")
        return "\n\n".join(lines)

    _doc_dir = str(Path(__file__).resolve().parents[2] / "doc")

    @_mcp.resource("opp-repl://guides")
    def guide_list() -> str:
        """List available opp_repl guide topics.

        Each topic can be read in full via opp-repl://guide/{topic}.
        """
        lines = []
        for path in sorted(glob.glob(os.path.join(_doc_dir, "*.md"))):
            topic = os.path.splitext(os.path.basename(path))[0]
            with open(path, "r") as f:
                content = f.read()
            # Skip the heading line(s) and grab the first paragraph
            para_lines = []
            past_heading = False
            for line in content.split("\n"):
                stripped = line.strip()
                if not past_heading:
                    if stripped.startswith("#") or stripped == "":
                        continue
                    past_heading = True
                if past_heading:
                    if stripped == "":
                        break
                    para_lines.append(stripped)
            summary = " ".join(para_lines) if para_lines else "(no description)"
            lines.append(f"{topic}\n    {summary}")
        return "\n\n".join(lines)

    @_mcp.resource("opp-repl://guide/{topic}")
    def guide(topic: str) -> str:
        """Read a specific opp_repl guide topic.

        Use opp-repl://guides to list available topics.
        """
        path = os.path.realpath(os.path.join(_doc_dir, f"{topic}.md"))
        if not path.startswith(os.path.realpath(_doc_dir) + os.sep) or not os.path.isfile(path):
            return f"Guide '{topic}' not found. Use opp-repl://guides to list available topics."
        with open(path, "r") as f:
            return f.read()

    @_mcp.resource("opp-repl://package/{package_name}")
    def api_reference(package_name: str) -> str:
        """Package documentation with class and function summaries.

        Shows the full package docstring, then for each public class its
        first paragraph and method one-line summaries, and for each public
        function its signature and one-line summary.  For full details, read:
        - opp-repl://class/{class_name}
        - opp-repl://method/{class_name}/{method_name}
        - opp-repl://function/{function_name}
        """
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
                summary = doc.split("\n")[0]
                lines.append(f"{name}{sig}\n    {summary}")
            elif inspect.isclass(obj):
                doc = inspect.getdoc(obj) or ""
                if not doc:
                    continue
                first_para = doc.split("\n\n")[0].replace("\n", " ")
                cls_lines = [f"class {name}\n    {first_para}"]
                for mname, mobj in inspect.getmembers(obj, predicate=inspect.isfunction):
                    if mname.startswith("_"):
                        continue
                    mmod = getattr(mobj, "__module__", None) or ""
                    if not mmod.startswith("opp_repl"):
                        continue
                    mdoc = inspect.getdoc(mobj) or ""
                    if not mdoc:
                        continue
                    msummary = mdoc.split("\n")[0]
                    cls_lines.append(f"    {mname}  -- {msummary}")
                lines.append("\n".join(cls_lines))
        return "\n\n".join(lines) if lines else f"No documented public API in '{package_name}'."

    @_mcp.resource("opp-repl://class/{class_name}")
    def class_doc(class_name: str) -> str:
        """Complete documentation for an opp_repl class.

        class_name may be fully qualified (e.g. opp_repl.simulation.workspace.SimulationWorkspace)
        or a short public name (e.g. SimulationWorkspace).
        Returns the full class docstring and public method signatures with
        first-paragraph summaries.  For full method documentation, read:
        - opp-repl://method/{class_name}/{method_name}
        """
        cls, qualified = _resolve_opp_repl_name(class_name, kind="class")
        if cls is None:
            return f"Class '{class_name}' not found among loaded opp_repl modules."
        lines = [f"class {qualified}"]
        try:
            sig = str(inspect.signature(cls))
        except (ValueError, TypeError):
            sig = "(...)"
        lines[0] += sig
        doc = inspect.getdoc(cls) or ""
        if doc:
            lines.append("")
            lines.extend("    " + l for l in doc.split("\n"))
        for mname, mobj in inspect.getmembers(cls, predicate=inspect.isfunction):
            if mname.startswith("_") and mname != "__init__":
                continue
            try:
                msig = str(inspect.signature(mobj))
            except (ValueError, TypeError):
                msig = "(...)"
            mdoc = inspect.getdoc(mobj) or ""
            entry = f"    {mname}{msig}"
            if mdoc:
                first_para = mdoc.split("\n\n")[0].replace("\n", " ")
                entry += f"\n        {first_para}"
            lines.append(entry)
        return "\n".join(lines)

    @_mcp.resource("opp-repl://method/{class_name}/{method_name}")
    def method_doc(class_name: str, method_name: str) -> str:
        """Documentation for a specific method of an opp_repl class.

        class_name may be fully qualified or a short public name.
        method_name is the plain method name (e.g. run).
        """
        cls, qualified = _resolve_opp_repl_name(class_name, kind="class")
        if cls is None:
            return f"Class '{class_name}' not found among loaded opp_repl modules."
        mobj = getattr(cls, method_name, None)
        if mobj is None:
            return f"Method '{method_name}' not found on class '{qualified}'."
        try:
            msig = str(inspect.signature(mobj))
        except (ValueError, TypeError):
            msig = "(...)"
        lines = [f"{qualified}.{method_name}{msig}"]
        mdoc = inspect.getdoc(mobj) or ""
        if mdoc:
            lines.append("")
            lines.extend("    " + l for l in mdoc.split("\n"))
        return "\n".join(lines)

    @_mcp.resource("opp-repl://function/{function_name}")
    def function_doc(function_name: str) -> str:
        """Documentation for an opp_repl function.

        function_name may be fully qualified (e.g. opp_repl.simulation.task.run_simulations)
        or a short public name (e.g. run_simulations).
        """
        func, qualified = _resolve_opp_repl_name(function_name, kind="function")
        if func is None:
            return f"Function '{function_name}' not found among loaded opp_repl modules."
        try:
            sig = str(inspect.signature(func))
        except (ValueError, TypeError):
            sig = "(...)"
        lines = [f"{qualified}{sig}"]
        doc = inspect.getdoc(func) or ""
        if doc:
            lines.append("")
            lines.extend("    " + l for l in doc.split("\n"))
        return "\n".join(lines)

    @_mcp.tool()
    def execute_python(code: str) -> str:
        """Execute Python code in the live IPython session.

        The code runs in the same namespace as the interactive REPL user.
        All public opp_repl packages, functions and classes are pre-loaded.

        IMPORTANT: Before writing any code, always read the documentation resources first.
        Do NOT guess function names, parameter names, or signatures. Look them up.
        Do NOT import packages that are already pre-loaded.
        Do NOT use print() to view results.

        To discover the documentation:
        - Read opp-repl://guides for a list of guide topics
        - Read opp-repl://guide/{topic} for a specific guide
        - Read opp-repl://packages for a list of sub-packages
        - Read opp-repl://package/{package_name} for package documentation
        - Read opp-repl://class/{class_name} for class documentation
        - Read opp-repl://method/{class_name}/{method_name} for method documentation
        - Read opp-repl://function/{function_name} for function documentation

        Args:
            code: Python code to execute.

        Returns:
            The repr of the last expression's value (if any), followed by any
            captured stdout/stderr. There is no need to call print().
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
