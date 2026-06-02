"""
This module provides an MCP (Model Context Protocol) server for the opp_repl Python library.

The server runs on a background thread and exposes a single ``execute_python`` tool that
executes arbitrary Python code in the live IPython session. The AI assistant shares the
same namespace as the interactive user, so all opp_repl functions (run_simulations,
compare_simulations, run_fingerprint_tests, etc.) are available directly.

================================================================================
Architecture of ``execute_python``
================================================================================

Goals
-----
1. The AI's code runs in the *same* IPython namespace as the interactive user
   (shared state, shared history, shared display hooks).
2. The cell appears in the terminal exactly like a user-typed cell:
   ``In [N]: <code>`` followed by live stdout/stderr/logging output and
   ``Out[N]: <repr>``.
3. The cell never interleaves with the live prompt redraw.
4. Stdout/stderr/logging are captured and returned to the MCP client, AND
   streamed line-by-line via ``ctx.info`` notifications while the cell runs.
5. Ctrl-C on the terminal interrupts the cell, and does NOT leak into the
   user's pending prompt after the cell finishes.
6. MCP-side cancellation (Stop button in the agent UI, or any
   ``notifications/cancelled``) interrupts the cell with the same
   semantics as a terminal Ctrl-C.
7. The MCP event loop is never blocked by a long-running cell.

Three threads are involved
--------------------------
* **MCP event-loop thread** — created by ``start_mcp_server``. Runs uvicorn /
  ``_mcp.run`` and awaits the ``execute_python`` coroutine.
* **Worker thread** — ``anyio.to_thread.run_sync(runner)`` hops off the MCP
  loop so the rest of the dispatch can do blocking work.
* **Main (REPL) thread** — where IPython and prompt_toolkit live. The cell
  must ultimately run here, otherwise output interleaves with the live
  prompt and Ctrl-C semantics get weird.

Dispatch path
-------------
``execute_python`` (MCP loop) → dedicated worker ``threading.Thread`` →
``asyncio.run_coroutine_threadsafe(_run_on_pt, pt_loop)`` (main thread) →
``async with in_terminal():`` (prompt suspended) →
``_run_execute_python_sync`` → ``ip.run_cell``.

The MCP loop waits for the worker via an ``asyncio.Event`` that the
worker sets through ``call_soon_threadsafe``. We manage the thread
ourselves (rather than via ``anyio.to_thread.run_sync``) so we can
interleave MCP cancellation handling — see below.

We can't use prompt_toolkit's sync ``run_in_terminal`` helper because it
calls ``ensure_future`` on the calling thread, which on the worker thread
has no event loop.

Why ``in_terminal``?
--------------------
It suspends the prompt and puts the tty in cooked mode for the duration of
the cell, so direct writes to the terminal are not garbled by the prompt
redraw and Ctrl-C reaches the main thread synchronously.

Output: ``_TeeStream`` + ``_CaptureSink``
-----------------------------------------
``sys.stdout`` / ``sys.stderr`` are replaced with ``_TeeStream`` that fans
writes out to (a) the *raw* interpreter-level streams ``sys.__stdout__`` /
``sys.__stderr__`` and (b) a ``_CaptureSink``.

We tee to ``__stdout__`` / ``__stderr__`` (NOT the current ``sys.stdout``)
because IPython at the prompt wraps stdout in prompt_toolkit's
``StdoutProxy``, which queues writes to a background thread that flushes
via ``run_in_terminal`` on the loop — and the loop is blocked by our cell.
Direct writes to the raw fd appear live because ``in_terminal`` already
put the tty in cooked mode.

``_TeeStream.fileno`` deliberately returns the *real terminal's* fd, so
``Vt100_Output.from_pty``'s terminal-size detection works. We deliberately
omit a ``buffer`` attribute so ``flush_stdout`` doesn't write directly to
the underlying buffer and bypass the fan-out.

``_CaptureSink`` ANSI-strips every write into an internal ``StringIO`` and,
when ``on_line`` is set, fires the callback once per complete line so the
MCP client can stream chunks.

Logging is captured by ``_StreamingLogHandler`` attached to the root
logger; it routes formatted records into the same sink (sink only, not the
terminal — existing handlers already write to the terminal).

Streaming to the MCP client
---------------------------
``on_line`` (created in ``execute_python``) closes over the MCP loop and
calls ``asyncio.run_coroutine_threadsafe(ctx.info(line), mcp_loop)`` to
hop each line back to the MCP thread as a log notification. The blocking
``fut.result(timeout=5.0)`` provides backpressure; failures (closed loop /
stream) silently drop the streamed chunk because the line is still
captured into the sink's buffer for the final return value.

Ctrl-C / SIGINT handling
------------------------
Two cooperating mechanisms make Ctrl-C work right:

1. **SIGINT handler swap** — asyncio's installed SIGINT handler only
   schedules a loop wake-up, but the cell runs synchronously inside the
   loop's current task and never yields, so without swapping in
   ``signal.default_int_handler`` Ctrl-C would be invisible to the cell.
   Restored in the ``finally`` BEFORE other cleanup, so a late-arriving
   Ctrl-C during cleanup routes back to the normal handler.

2. **Wakeup fd redirection** — CPython's C-level signal handler writes a
   byte to whatever fd is registered via ``signal.set_wakeup_fd`` on
   every signal. asyncio registers its csock there, so a Ctrl-C during
   the cell would (a) raise ``KeyboardInterrupt`` synchronously via the
   handler above (good) and (b) leave a pending byte in asyncio's csock.
   Once the cell returns and the loop resumes, that byte makes the loop
   invoke prompt_toolkit's registered SIGINT callback, which raises
   ``KeyboardInterrupt`` at the prompt and surfaces as
   ``"KeyboardInterrupt escaped interact()"``. We redirect the wakeup fd
   to a private pipe for the duration of the cell, then close it on
   exit so any byte dies with it.

A safety-net ``except KeyboardInterrupt`` around the cleanup catches a
Ctrl-C that slips through after SIGINT is restored to default-int but
before the finally chain finishes; the user's intent was already honored
by the cell-level handler, so we swallow it.

MCP-side cancellation
---------------------
When the agent UI sends ``notifications/cancelled``, FastMCP cancels the
``execute_python`` coroutine, surfacing as ``asyncio.CancelledError`` on
our ``await done_event.wait()``. The cell is still running on the main
thread at this point. We deliver SIGINT to our own process via
``os.kill(os.getpid(), signal.SIGINT)`` — CPython routes the signal to
the main thread, where ``default_int_handler`` is installed for the
cell's duration, so ``KeyboardInterrupt`` raises inside ``ip.run_cell``
exactly as it would for a terminal Ctrl-C. After signalling we
``asyncio.shield(done_event.wait())`` to let the cell wind down (signal
handler restore, AppSession restore, etc.) before re-raising the
``CancelledError`` to the MCP framework, so the REPL is in a clean state
on return.

The window where SIGINT is meaningful is exactly the window where we've
installed ``default_int_handler`` (inside ``in_terminal()``). Before or
after that window the signal routes to asyncio's normal SIGINT handler,
which is also correct — though it means cancellation arriving during the
narrow setup/teardown around the cell may not interrupt the cell itself.

AppSession tweaks during the cell
---------------------------------
* ``_session._output = None`` — forces prompt_toolkit to recreate its
  cached ``Output``, so IPython's display hook's ``Out[N]:`` line routes
  through the current ``sys.stdout`` tee instead of a stale ``Output``
  bound to a previous prompt cycle's stdout.
* ``_session.app = None`` — ``print_formatted_text`` (used by IPython's
  display hook) otherwise sees a running app and *defers* its render via
  ``loop.call_soon_threadsafe(lambda: run_in_terminal(render))``, which
  never fires because the loop is blocked by our cell. With no app
  visible, the helper renders inline through our restored
  ``AppSession.output`` (= our tee), so styled output appears live before
  the next prompt redraw.

Prompt redraw after the cell
----------------------------
Our cell incremented ``execution_count``, but the user's pending prompt
was rendered with pre-evaluated message text (IPython caches it for CPU
efficiency in default emacs mode). We swap in a callable for
``pt_app.message`` that re-fetches the tokens, so ``in_terminal``'s
exit-redraw picks up the fresh count in one draw — no double-redraw
flicker.

Return value
------------
``sink.getvalue()`` (rstrip'd) followed by any ``error_in_exec`` /
``error_before_exec``. We deliberately do NOT append the cell's result
repr separately: ``ip.run_cell(..., silent=False)`` already ran the
display hook and ``Out[N]: <repr>`` was captured into the sink. Appending
it again would duplicate the value.

Fallback path
-------------
If there's no live prompt_toolkit app (simple-prompt mode, tests, or
between-prompts state), ``runner()`` executes ``_run_execute_python_sync``
directly on the worker thread, skipping all the ``in_terminal`` /
signal / AppSession plumbing.
"""

import asyncio
import atexit
import glob
import hashlib
import hmac
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

from opp_repl.common.util import is_running_in_sandbox

try:
    from mcp.server.fastmcp import FastMCP, Context
    import anyio
    _mcp_available = True
except ImportError:
    _mcp_available = False

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

mcp_calls = []

_ANSI_RE = re.compile(
    # CSI: ESC [ params (0x30-0x3F) intermediates (0x20-0x2F) final (0x40-0x7E)
    r"\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]"
    # OSC: ESC ] ... terminator (BEL or ESC\)
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    # Single-char ESC sequence (C1 controls: ESC followed by one byte in @-_)
    r"|\x1b[@-_]"
)

def _strip_ansi(text):
    return _ANSI_RE.sub("", str(text))


class _TeeStream:
    """File-like that fans writes out to multiple streams. Writes never raise."""
    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            try:
                s.write(data)
            except Exception:
                pass
        return len(data) if isinstance(data, str) else 0

    def flush(self):
        for s in self._streams:
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self):
        for s in self._streams:
            try:
                if s.isatty():
                    return True
            except Exception:
                pass
        return False

    def writable(self):
        return True

    def fileno(self):
        # Return the fd of the first underlying stream that has one (the
        # real terminal in our case). prompt_toolkit's Vt100_Output.from_pty
        # uses this for terminal-size detection. We deliberately don't
        # expose a `buffer` attribute — flush_stdout would otherwise write
        # to it directly and bypass our fan-out to the sink.
        for s in self._streams:
            try:
                return s.fileno()
            except (AttributeError, OSError, io.UnsupportedOperation):
                continue
        raise io.UnsupportedOperation("fileno")

    @property
    def encoding(self):
        for s in self._streams:
            enc = getattr(s, "encoding", None)
            if enc:
                return enc
        return "utf-8"


class _CaptureSink:
    """File-like that captures writes into a buffer with ANSI stripped, and
    fires a callback for each completed line (used to stream chunks to the
    MCP client)."""
    def __init__(self, on_line=None):
        self._buf = io.StringIO()
        self._partial = ""
        self._on_line = on_line

    def write(self, data):
        if not data:
            return 0
        clean = _strip_ansi(data)
        self._buf.write(clean)
        if self._on_line is not None:
            self._partial += clean
            while "\n" in self._partial:
                line, self._partial = self._partial.split("\n", 1)
                self._on_line(line)
        return len(data)

    def flush(self):
        if self._on_line is not None and self._partial:
            self._on_line(self._partial)
            self._partial = ""

    def getvalue(self):
        return self._buf.getvalue()


class _StreamingLogHandler(logging.Handler):
    """Forwards formatted log records into a _CaptureSink so logging output is
    captured alongside stdout/stderr (and streamed line-by-line to MCP)."""
    def __init__(self, sink):
        super().__init__()
        self._sink = sink
        self.setFormatter(logging.Formatter("%(name)s %(levelname)s: %(message)s"))

    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            return
        if not msg.endswith("\n"):
            msg += "\n"
        try:
            self._sink.write(msg)
        except Exception:
            pass


def _run_execute_python_sync(code, sink):
    """Run a snippet with stdout/stderr/logging tee'd to the REPL console and
    captured into ``sink``. Normally invoked on the main thread via
    ``prompt_toolkit.application.run_in_terminal`` (with the prompt suspended);
    falls back to a worker-thread call when no prompt_toolkit app is running.
    """
    import IPython
    ip = IPython.get_ipython()

    # Defensive: on Python 3.14+ asyncio.get_event_loop() is strict and raises
    # on threads without a loop. IPython's autoawait helper may want one, and
    # we run in three different threads (event-loop thread, worker thread,
    # main thread inside run_in_terminal) depending on the dispatch path.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    old_pager = pydoc.pager
    pydoc.pager = pydoc.plainpager

    # When the REPL is at the prompt, IPython has wrapped sys.stdout/stderr
    # in prompt_toolkit's StdoutProxy. That proxy queues writes onto a
    # background thread which flushes them via `run_in_terminal` on the
    # loop — which never gets to run while our cell is blocking the loop,
    # so the user sees nothing until we return. Tee to the underlying
    # interpreter-level streams instead; the in_terminal context already
    # suspended the prompt and put the tty in cooked mode, so direct
    # writes appear live.
    real_stdout = sys.__stdout__ or sys.stdout
    real_stderr = sys.__stderr__ or sys.stderr
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = _TeeStream(real_stdout, sink)
    sys.stderr = _TeeStream(real_stderr, sink)

    log_handler = _StreamingLogHandler(sink)
    log_handler.setLevel(logging.NOTSET)
    root_logger = logging.getLogger()
    root_logger.addHandler(log_handler)

    info = {}
    try:
        if ip is not None:
            # Echo "In [N]: <code>" to the terminal so an MCP-initiated cell
            # looks the same as one the user typed. Use IPython's prompt
            # tokens + style so the colors match exactly.
            try:
                from prompt_toolkit.formatted_text import PygmentsTokens
                from prompt_toolkit.shortcuts import print_formatted_text
                tokens = ip.prompts.in_prompt_tokens()
                style = getattr(ip, "_style", None)
                print_formatted_text(PygmentsTokens(tokens), end="", style=style)
            except Exception:
                print(f"In [{ip.execution_count}]: ", end="")
            print(code)
            try:
                result = ip.run_cell(code, silent=False, store_history=True)
                if result.error_in_exec is not None:
                    info["error_in_exec"] = _strip_ansi(str(result.error_in_exec))
                if result.error_before_exec is not None:
                    info["error_before_exec"] = _strip_ansi(str(result.error_before_exec))
            except KeyboardInterrupt:
                info["interrupted"] = True
        else:
            # Fallback: no IPython session (e.g. testing outside the REPL)
            namespace = {"__builtins__": __builtins__}
            exec("from opp_repl import *", namespace)
            try:
                try:
                    result = eval(code, namespace)
                    if result is not None:
                        print(repr(result))
                except SyntaxError:
                    exec(code, namespace)
            except KeyboardInterrupt:
                info["interrupted"] = True
            except Exception:
                traceback.print_exc(file=sys.stderr)
    finally:
        try:
            sink.flush()
        except Exception:
            pass
        root_logger.removeHandler(log_handler)
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        pydoc.pager = old_pager
    return info


if _mcp_available:
    _mcp = FastMCP("opp_repl", host="127.0.0.1", port=9966, stateless_http=True,
                    instructions="""\
opp_repl is a Python toolkit for working with OMNeT++ discrete event simulations:
building, running, analyzing, testing, and more.

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
    async def execute_python(code: str, ctx: Context | None = None) -> str:
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
            captured stdout/stderr/logging output. There is no need to call print().
            Output is also streamed to the MCP client line-by-line as log
            notifications while the code is running, and printed to the REPL
            console in real time.
        """
        mcp_calls.append({"tool": "execute_python", "code": code})

        mcp_loop = asyncio.get_running_loop()

        def on_line(line):
            if ctx is None:
                return
            try:
                fut = asyncio.run_coroutine_threadsafe(ctx.info(line), mcp_loop)
                fut.result(timeout=5.0)
            except Exception:
                # MCP loop closed, stream closed, or no portal — drop the
                # streamed chunk; the line is still captured into the buffer
                # for the final return value.
                pass

        sink = _CaptureSink(on_line=on_line if ctx is not None else None)

        # Run the snippet on the main thread (where the interactive user's
        # IPython REPL lives) by scheduling it onto prompt_toolkit's event
        # loop and asking it to suspend the prompt for the duration. This
        # prevents output from interleaving with whatever the user is doing,
        # and lets a Ctrl-C from the terminal interrupt the cell naturally
        # via SIGINT on the main thread.
        def runner():
            import IPython
            ip = IPython.get_ipython()
            pt_app = getattr(ip, "pt_app", None)
            app = getattr(pt_app, "app", None) if pt_app is not None else None
            loop = getattr(app, "loop", None) if app is not None else None
            if app is None or loop is None or not getattr(app, "is_running", False):
                # Fallback: no live prompt_toolkit app (simple-prompt mode,
                # tests, between-prompts state) — execute synchronously here.
                return _run_execute_python_sync(code, sink)
            # Build a coroutine that, when driven on the prompt_toolkit loop,
            # enters the `in_terminal` async context manager (which suspends
            # the prompt) and runs the cell synchronously on the loop's
            # thread — the same main thread the interactive user is on. We
            # can't use prompt_toolkit's sync `run_in_terminal` helper here
            # because it internally calls `ensure_future` on the *calling*
            # thread, which on a worker thread has no loop.
            from prompt_toolkit.application import in_terminal
            from prompt_toolkit.application.current import get_app_session
            from prompt_toolkit.formatted_text import PygmentsTokens
            import os as _os
            import signal as _signal
            async def _run_on_pt():
                async with in_terminal():
                    # Redirect the process-wide signal wakeup fd to a
                    # private pipe for the duration of the cell. CPython's
                    # C-level signal handler unconditionally writes to
                    # whatever wakeup fd is registered when a signal is
                    # delivered — including SIGINT — *regardless* of the
                    # Python-level handler. Without this redirection a
                    # Ctrl-C during our blocking cell would (a) raise
                    # KeyboardInterrupt synchronously via the Python
                    # handler we install just below (good), AND (b) leave a
                    # pending byte in the asyncio loop's csock; once we
                    # exit and the loop resumes, that byte makes the loop
                    # invoke prompt_toolkit's registered SIGINT callback,
                    # which raises KeyboardInterrupt at the prompt and
                    # surfaces as "KeyboardInterrupt escaped interact()".
                    _wake_r_fd, _wake_w_fd = _os.pipe()
                    try:
                        _os.set_blocking(_wake_w_fd, False)
                    except Exception:
                        pass
                    try:
                        _saved_wakeup_fd = _signal.set_wakeup_fd(_wake_w_fd)
                    except Exception:
                        _saved_wakeup_fd = -1
                    # Install the default SIGINT handler (raises
                    # KeyboardInterrupt) for the duration of the cell.
                    # asyncio's installed handler only schedules a loop
                    # wake-up, but our cell runs synchronously inside the
                    # loop's current task and never yields, so without this
                    # swap Ctrl-C is invisible to the cell.
                    _old_sigint = _signal.signal(
                        _signal.SIGINT, _signal.default_int_handler
                    )
                    # Force prompt_toolkit's AppSession to recreate its
                    # cached Output, so the display hook's `Out[N]:` print
                    # routes through our current sys.stdout tee (live to
                    # the terminal and captured into the sink). A stale
                    # cached Output bound to a previous prompt cycle's
                    # stdout would write somewhere we can't see.
                    _session = get_app_session()
                    _saved_session_output = _session._output
                    _session._output = None
                    # Detach the running app from the AppSession during the
                    # cell. `print_formatted_text` (used by IPython's display
                    # hook for `Out[N]:`) otherwise sees a running app and
                    # *defers* its render via `loop.call_soon_threadsafe(
                    # lambda: run_in_terminal(render))` — which never fires
                    # because the loop is blocked by our sync cell. With no
                    # app visible, the helper renders inline through our
                    # restored AppSession.output (= our tee), so the styled
                    # `Out[N]:` appears live before the next prompt redraw.
                    _saved_session_app = _session.app
                    _session.app = None
                    result = None
                    try:
                        try:
                            result = _run_execute_python_sync(code, sink)
                        finally:
                            # Restore the signal handler FIRST so that any
                            # late-arriving SIGINT after the cell returns
                            # routes to the prompt_toolkit/asyncio handler
                            # rather than raising KeyboardInterrupt in main
                            # thread mid-cleanup.
                            try:
                                _signal.signal(_signal.SIGINT, _old_sigint)
                            except Exception:
                                pass
                            # Restore the wakeup fd to whatever asyncio had
                            # before and discard our private pipe (any
                            # bytes written into it by SIGINT during the
                            # cell die with it, so the loop never sees a
                            # phantom signal).
                            try:
                                _signal.set_wakeup_fd(_saved_wakeup_fd)
                            except Exception:
                                pass
                            try:
                                _os.close(_wake_r_fd)
                            except Exception:
                                pass
                            try:
                                _os.close(_wake_w_fd)
                            except Exception:
                                pass
                            try:
                                _session.app = _saved_session_app
                            except Exception:
                                pass
                            try:
                                _session._output = _saved_session_output
                            except Exception:
                                pass
                    except KeyboardInterrupt:
                        # A KeyboardInterrupt that slipped through the
                        # cleanup window (signal still default-int while a
                        # finally clause was running). The cell itself was
                        # either completed or already records the interrupt
                        # via run_cell; swallow here so it doesn't propagate
                        # to IPython's mainloop and trigger the escape
                        # message. The user's intent (interrupt the cell)
                        # has already been honored.
                        if result is None:
                            result = {"interrupted": True}
                    # Our cell incremented execution_count, but the user's
                    # pending prompt was rendered with a pre-evaluated
                    # message (IPython caches the message text in default
                    # emacs mode for CPU efficiency). Swap in a callable
                    # that re-fetches the tokens now, while we're still
                    # inside `in_terminal` so its own exit-redraw picks up
                    # the fresh count in one draw (no double-redraw
                    # flicker/garble).
                    try:
                        pt_app.message = lambda: PygmentsTokens(
                            ip.prompts.in_prompt_tokens()
                        )
                    except Exception:
                        pass
                return result
            cf_future = asyncio.run_coroutine_threadsafe(_run_on_pt(), loop)
            return cf_future.result()

        # Run the snippet in a dedicated worker thread, observed via an
        # asyncio.Event. We manage this ourselves (rather than via
        # anyio.to_thread.run_sync) so we can react to MCP cancellation
        # — e.g. the Stop button in the agent UI sends a
        # notifications/cancelled which FastMCP turns into an
        # asyncio.CancelledError on our task — by injecting Ctrl-C into
        # the main thread before the worker has finished.
        done_event = asyncio.Event()
        result_box = {}

        def _worker():
            try:
                result_box["info"] = runner()
            except BaseException as e:
                result_box["exc"] = e
            finally:
                mcp_loop.call_soon_threadsafe(done_event.set)

        worker_thread = threading.Thread(
            target=_worker, daemon=True, name="opp-repl-mcp-execute"
        )
        worker_thread.start()

        try:
            await done_event.wait()
        except asyncio.CancelledError:
            # MCP client cancelled. Inject Ctrl-C into the main thread —
            # same mechanism as a terminal Ctrl-C. The cell, running
            # inside in_terminal() with default_int_handler installed,
            # raises KeyboardInterrupt at the next bytecode boundary;
            # ip.run_cell records it and the cleanup path runs.
            try:
                os.kill(os.getpid(), signal.SIGINT)
            except Exception:
                pass
            # Wait for the cell to wind down before propagating, so the
            # REPL is back in a clean state when we return. Shield so a
            # double-cancel can't strand us mid-cleanup.
            try:
                await asyncio.shield(done_event.wait())
            except BaseException:
                pass
            raise

        if "exc" in result_box:
            raise result_box["exc"]
        info = result_box["info"]

        if info.get("interrupted"):
            text = "Interrupted by user (Ctrl-C)"
            _logger.info(text)
            return text

        parts = []
        output = sink.getvalue()
        if output:
            parts.append(output.rstrip())
        # Skip info["result_repr"] — IPython's display hook already prints the
        # last expression's value (as ``Out[N]: <repr>``) when silent=False,
        # and that line is captured into ``sink`` above. Including it again
        # would duplicate the value in the response.
        if info.get("error_in_exec") is not None:
            parts.append(info["error_in_exec"])
        if info.get("error_before_exec") is not None:
            parts.append(info["error_before_exec"])
        text = "\n".join(parts) if parts else "(no output)"
        return text

if _mcp_available:
    _register_mcp_handlers()

class _HashTokenVerifier:
    """Bearer token verifier that stores only the SHA-256 hash of the expected token.

    On each request the incoming raw token is hashed and compared to the
    stored hash using a timing-safe comparison.
    """

    def __init__(self, expected_hash_hex: str):
        self._expected_hash_hex = expected_hash_hex.lower()

    async def verify_token(self, token: str):
        from mcp.server.auth.provider import AccessToken
        incoming_hash = hashlib.sha256(token.encode()).hexdigest()
        if hmac.compare_digest(incoming_hash, self._expected_hash_hex):
            return AccessToken(token=token, client_id="opp_repl", scopes=[])
        return None

def _default_socket_path():
    """Return the stable per-user default Unix domain socket path.

    Uses ``$XDG_RUNTIME_DIR/opp_repl/mcp.sock`` when available, falling back
    to ``/tmp/opp_repl-<uid>/mcp.sock``.  Parent directory is created with
    mode ``0700`` (owner-only).
    """
    xdg = os.environ.get("XDG_RUNTIME_DIR", "")
    if xdg and os.path.isdir(xdg):
        base = os.path.join(xdg, "opp_repl")
    else:
        base = os.path.join("/tmp", f"opp_repl-{os.getuid()}")
    os.makedirs(base, mode=0o700, exist_ok=True)
    # mode= in makedirs is ignored when the dir pre-exists; chmod unconditionally
    # so the parent is always 0700 regardless of prior umask or stale dirs.
    try:
        os.chmod(base, 0o700)
    except OSError:
        pass
    return os.path.join(base, "mcp.sock")


_cleanup_socket_path = None


def _remove_socket_file():
    """atexit handler: remove the UDS socket file on clean exit."""
    path = _cleanup_socket_path
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass


atexit.register(_remove_socket_file)


_SOCKET_PATH_NOT_SET = object()  # sentinel: socket_path was not passed → TCP mode


def start_mcp_server(port=9966, socket_path=_SOCKET_PATH_NOT_SET, token_hash=None, bypass_token_hash_check=False):
    """Start the MCP server on a background thread.

    When ``socket_path`` is given (or ``None`` to use the default per-user
    path), the server listens on a Unix domain socket.  The socket is created
    with mode ``0600`` so only the owning user can connect — no bearer token
    is required.  Run ``opp_repl_mcp --help`` to see the resolved path and
    ready-to-paste client configuration snippets.

    When ``socket_path`` is not used the server listens on a TCP port using
    Streamable HTTP (stateless mode).  Each tool call is an independent HTTP
    POST request — no persistent connection is required.

    Endpoint (TCP mode): http://127.0.0.1:{port}/mcp

    Args:
        port: TCP port to listen on (default 9966).  Ignored when
            ``socket_path`` is supplied.
        socket_path: Unix domain socket path.  Pass ``None`` to use the
            stable per-user default path.  When supplied the server runs in
            UDS mode and bearer-token authentication is skipped.
        token_hash: Hex-encoded SHA-256 hash of the bearer token that
            clients must present (TCP mode only).  Required unless the server
            is running inside ``opp_sandbox``.
        bypass_token_hash_check: When True, start the TCP server without
            bearer token authentication even outside ``opp_sandbox``.
            Intended for trusted environments only.
    """
    if not _mcp_available:
        raise ImportError("MCP server requires the 'mcp' package. Install it with: pip install opp_repl[mcp]")

    global _cleanup_socket_path

    logging.getLogger("mcp").setLevel(logging.WARNING)

    uds_mode = socket_path is not _SOCKET_PATH_NOT_SET

    if uds_mode:
        # --- Unix domain socket mode ---
        if socket_path is None:
            socket_path = _default_socket_path()

        # Stale-socket reclaim: only act on actual sockets, never regular files
        # or symlinks. Refuse to start if the path exists but isn't a socket.
        if os.path.lexists(socket_path):
            import stat as _stat
            try:
                st = os.lstat(socket_path)
            except OSError as e:
                raise RuntimeError(f"Cannot stat {socket_path}: {e}") from e
            if not _stat.S_ISSOCK(st.st_mode):
                raise RuntimeError(
                    f"{socket_path} exists and is not a Unix socket "
                    f"(mode={oct(st.st_mode)}); refusing to remove."
                )
            import socket as _sock
            _probe = _sock.socket(_sock.AF_UNIX, _sock.SOCK_STREAM)
            try:
                _probe.connect(socket_path)
                _probe.close()
                raise RuntimeError(
                    f"Another opp_repl MCP server is already running at {socket_path}. "
                    f"Stop it first, or delete the socket file manually."
                )
            except OSError:
                _logger.warning(f"Removing stale MCP socket: {socket_path}")
                try:
                    os.unlink(socket_path)
                except OSError:
                    pass
            finally:
                try:
                    _probe.close()
                except Exception:
                    pass

        # Disable DNS rebinding protection for UDS: the socket's 0600 filesystem
        # permissions already prevent any external access; the Host header check
        # is meaningless over a Unix socket and would reject all clients.
        from mcp.server.transport_security import TransportSecuritySettings
        _mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )

        startup_event = threading.Event()
        startup_error = []

        def _run_uds():
            try:
                import uvicorn

                class _ChmodServer(uvicorn.Server):
                    async def startup(self, sockets=None):
                        # Restrict umask so the socket is created at 0600 from the
                        # start, closing the TOCTOU window between bind() and chmod.
                        old_umask = os.umask(0o077)
                        try:
                            await super().startup(sockets=sockets)
                        finally:
                            os.umask(old_umask)
                        # Belt-and-suspenders: enforce 0600 even if umask was bypassed.
                        if os.path.exists(socket_path):
                            os.chmod(socket_path, 0o600)
                        startup_event.set()

                async def _serve():
                    app = _mcp.streamable_http_app()
                    config = uvicorn.Config(app, uds=socket_path, log_level="warning")
                    server = _ChmodServer(config)
                    await server.serve()

                anyio.run(_serve)
            except Exception as e:
                startup_error.append(e)
                _logger.error(f"MCP server (UDS) failed: {e}")
            finally:
                # Wake start_mcp_server even if startup() never reached set()
                startup_event.set()

        thread = threading.Thread(target=_run_uds, daemon=True, name="opp-repl-mcp-server")
        thread.start()
        if not startup_event.wait(timeout=10.0):
            raise RuntimeError(
                f"MCP server (UDS) did not finish startup within 10 seconds at {socket_path}"
            )
        if startup_error:
            raise startup_error[0]
        # Only arm cleanup once we know bind succeeded; otherwise atexit could
        # unlink a socket owned by a later, unrelated process on the same path.
        _cleanup_socket_path = socket_path
        _logger.info(
            f"MCP server listening on Unix socket {socket_path}"
        )
        _logger.info(
            f"Run 'opp_repl_mcp --help' for client configuration examples."
        )
        return thread

    else:
        # --- TCP / Streamable-HTTP mode ---
        if not token_hash and not bypass_token_hash_check and not is_running_in_sandbox():
            raise ValueError(
                "Cannot start MCP server: no authentication configured. "
                "Outside opp_sandbox the MCP server requires either "
                "--mcp-token-hash (bearer token authentication) or "
                "--mcp-bypass-token-hash-check (disable authentication; trusted environments only). "
                "To generate a token hash, run: echo -n your_passphrase | sha256sum | cut -d' ' -f1 "
                "then pass the resulting hex hash via --mcp-token-hash, and configure the same "
                "passphrase as the bearer token in your MCP client (e.g. Windsurf). "
                "Alternatively, pass --mcp-bypass-token-hash-check to disable authentication entirely "
                "(only safe in trusted local environments), or run opp_repl inside opp_sandbox where "
                "the bubblewrap sandbox provides filesystem-level isolation and authentication is skipped."
            )
        if bypass_token_hash_check and token_hash:
            _logger.warning("--mcp-bypass-token-hash-check overrides --mcp-token-hash; starting MCP server without authentication")
            token_hash = None

        if token_hash:
            _mcp._token_verifier = _HashTokenVerifier(token_hash)
            from mcp.server.auth.settings import AuthSettings
            _mcp.settings.auth = AuthSettings(
                issuer_url="http://127.0.0.1",
                resource_server_url=f"http://127.0.0.1:{port}",
            )

        _mcp.settings.port = port
        _mcp.settings.log_level = "WARNING"

        def _run_tcp():
            try:
                _mcp.run(transport="streamable-http")
            except Exception as e:
                _logger.error(f"MCP server failed: {e}")

        thread = threading.Thread(target=_run_tcp, daemon=True, name="opp-repl-mcp-server")
        thread.start()
        _logger.info(f"MCP server started on port {port}")
        return thread
