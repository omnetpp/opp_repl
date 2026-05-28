"""
Module-image capture and tests.

Three public functions:

- :py:func:`capture_module_images` — launch each filtered simulation in
  Qtenv with its MCP server enabled, capture a PNG image of every
  compound module that matches the include/exclude filters, and write
  the images into an output directory.
- :py:func:`update_module_image_test_results` — same capture, but the
  output directory defaults to the project's
  ``module_image_baseline_folder``, and the results are reported as
  INSERT / KEEP / UPDATE just like chart-test updates.
- :py:func:`run_module_image_tests` — render fresh images, compare them
  against the project's baseline (or a different
  ``baseline_simulation_project``), and report PASS / FAIL with a
  per-image RMSE metric.  Mirrors :py:func:`run_chart_tests`.

The simulations are launched in Qtenv with
``--mcp-server-address localhost:<port>`` and the Qt platform forced to
``offscreen``.  Images are captured at simulation time t=0, immediately
after the network has been built and before any event runs.
"""

import base64
import copy
import fnmatch
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

from opp_repl.common import *
from opp_repl.common.mcp_client import QtenvMCPClient, wait_for_mcp_ready
from opp_repl.simulation.project import *
from opp_repl.simulation.task import *
from opp_repl.test.task import *

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filename + grouping helpers
# ---------------------------------------------------------------------------

_FILENAME_SEP = "__"


def _sanitize_field(value):
    """Make a single filename field safe to drop into a flat directory."""
    return value.replace("/", "_").replace("\\", "_")


def _compute_group_key(full_path, ned_type, group_by):
    if group_by == "path":
        return full_path
    elif group_by == "type":
        return ned_type
    elif group_by == "path_no_indices":
        return re.sub(r"\[\d+\]", "", full_path)
    else:
        raise ValueError(f"Unknown group_by: {group_by!r} (expected 'path', 'type', or 'path_no_indices')")


def _compose_image_filename(working_directory, config, run_number, group_key):
    """Build the unique per-image filename (without extension)."""
    parts = [
        _sanitize_field(working_directory),
        _sanitize_field(config),
        f"r{run_number}",
        _sanitize_field(group_key),
    ]
    return _FILENAME_SEP.join(parts) + ".png"


def _walk_compound_modules(topology_node, results=None):
    """Recursively collect every node that has at least one submodule.

    Returns a list of ``(full_path, ned_type)`` tuples in pre-order
    traversal (parents before children).
    """
    if results is None:
        results = []
    submodules = topology_node.get("submodules") or []
    if submodules:
        results.append((topology_node["fullPath"], topology_node.get("type", "")))
    for sub in submodules:
        _walk_compound_modules(sub, results)
    return results


def _filter_and_group(modules, module_path_filter, exclude_module_path_filter,
                     module_type_filter, exclude_module_type_filter, group_by):
    """Apply include/exclude filters and group to a flat module list.

    Returns a list of ``(group_key, full_path, ned_type)`` tuples,
    one per group, preserving the order of first encounter.
    """
    seen = set()
    grouped = []
    for full_path, ned_type in modules:
        if module_path_filter and not fnmatch.fnmatchcase(full_path, module_path_filter):
            continue
        if exclude_module_path_filter and fnmatch.fnmatchcase(full_path, exclude_module_path_filter):
            continue
        if module_type_filter and not fnmatch.fnmatchcase(ned_type, module_type_filter):
            continue
        if exclude_module_type_filter and fnmatch.fnmatchcase(ned_type, exclude_module_type_filter):
            continue
        group_key = _compute_group_key(full_path, ned_type, group_by)
        if group_key in seen:
            continue
        seen.add(group_key)
        grouped.append((group_key, full_path, ned_type))
    return grouped


# ---------------------------------------------------------------------------
# Port preassignment
# ---------------------------------------------------------------------------

def _assign_mcp_ports(tasks, port_range=None):
    """Hand a distinct free TCP port to every task by holding sockets open.

    Binds one socket per task to ``127.0.0.1:0`` (or to a random port
    inside ``port_range`` when given) and keeps them all open until the
    full port list has been recorded.  The kernel guarantees uniqueness
    of simultaneously held sockets, so every task gets a distinct port.
    The sockets are closed right before the function returns; a small
    race window between close and the child binding remains, handled at
    rerun time.
    """
    sockets = []
    try:
        for task in tasks:
            if port_range:
                low, high = port_range
                # try every port in the range until one binds
                last_error = None
                bound = False
                import random
                candidates = list(range(low, high + 1))
                random.shuffle(candidates)
                for candidate in candidates:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
                    try:
                        s.bind(("127.0.0.1", candidate))
                        sockets.append(s)
                        task.mcp_port = candidate
                        bound = True
                        break
                    except OSError as e:
                        last_error = e
                        s.close()
                if not bound:
                    raise RuntimeError(
                        f"Could not allocate {len(tasks)} ports in range {port_range}: {last_error}"
                    )
            else:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("127.0.0.1", 0))
                sockets.append(s)
                task.mcp_port = s.getsockname()[1]
    finally:
        for s in sockets:
            try:
                s.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Per-image result detail (carried inside the per-simulation task result)
# ---------------------------------------------------------------------------

class ModuleImageResult:
    """Per-module-group outcome inside a per-simulation task result."""

    def __init__(self, group_key, module_path, ned_type, filename, status,
                 reason=None, metric=None):
        self.group_key = group_key
        self.module_path = module_path
        self.ned_type = ned_type
        self.filename = filename
        self.status = status
        self.reason = reason
        self.metric = metric

    def __repr__(self):
        bits = [f"status={self.status}", f"file={self.filename}"]
        if self.reason:
            bits.append(f"reason={self.reason!r}")
        if self.metric is not None:
            bits.append(f"metric={self.metric}")
        return "ModuleImageResult(" + ", ".join(bits) + ")"


# ---------------------------------------------------------------------------
# Capture: write each captured image to output_dir
# ---------------------------------------------------------------------------

class ModuleImageCaptureTaskResult(TaskResult):
    """Result of a single-simulation module-image capture.

    Carries an ``image_results`` list of :class:`ModuleImageResult`
    entries.  The aggregate ``result`` is ``"DONE"`` when every image
    was written successfully and the simulation terminated cleanly;
    ``"ERROR"`` if the simulation failed to launch or any image capture
    raised; ``"CANCEL"`` on Ctrl-C.
    """

    def __init__(self, task=None, result="DONE", image_results=None,
                 possible_results=["DONE", "SKIP", "CANCEL", "ERROR"],
                 possible_result_colors=[COLOR_GREEN, COLOR_CYAN, COLOR_CYAN, COLOR_RED],
                 **kwargs):
        super().__init__(task=task, result=result, possible_results=possible_results,
                         possible_result_colors=possible_result_colors, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.image_results = image_results or []


class MultipleModuleImageCaptureTaskResults(MultipleTaskResults):
    def __init__(self, multiple_tasks=None, results=[], expected_result="DONE",
                 possible_results=["DONE", "SKIP", "CANCEL", "ERROR"],
                 possible_result_colors=[COLOR_GREEN, COLOR_CYAN, COLOR_CYAN, COLOR_RED],
                 **kwargs):
        super().__init__(multiple_tasks=multiple_tasks, results=results,
                         expected_result=expected_result,
                         possible_results=possible_results,
                         possible_result_colors=possible_result_colors, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs

    def get_error_results(self, exclude_expected=True):
        return self.filter_results(result_filter="ERROR",
                                   exclude_expected_result_filter="ERROR" if exclude_expected else None)


# ---------------------------------------------------------------------------
# Update: compare to baseline, insert/keep/update
# ---------------------------------------------------------------------------

class ModuleImageUpdateTaskResult(UpdateTaskResult):
    """Aggregate update result for one simulation.

    ``result`` is the worst case across the per-image outcomes: ``ERROR``
    if anything errored, otherwise ``UPDATE`` if anything changed,
    otherwise ``INSERT`` if anything was newly written, otherwise
    ``KEEP``.
    """

    def __init__(self, task=None, result="KEEP", image_results=None, **kwargs):
        super().__init__(task=task, result=result, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.image_results = image_results or []


# ---------------------------------------------------------------------------
# Test: compare to baseline, PASS/FAIL with RMSE
# ---------------------------------------------------------------------------

class ModuleImageTestTaskResult(TestTaskResult):
    """Aggregate test result for one simulation.

    ``result`` aggregates the per-image verdicts: ``ERROR`` if the sim
    failed or any image errored, ``FAIL`` if any image failed,
    ``SKIP`` if the simulation produced no eligible modules,
    ``PASS`` otherwise.
    """

    def __init__(self, task=None, result="PASS", image_results=None, **kwargs):
        super().__init__(task=task, result=result, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.image_results = image_results or []

    def recheck(self, metric_threshold=0, **kwargs):
        """Recompute the aggregate verdict using a different RMSE threshold.

        Per-image metrics are preserved on the result, so the verdict
        can change without re-rendering anything.
        """
        new_result = copy.copy(self)
        new_result.image_results = list(self.image_results)
        had_error = False
        any_fail = False
        any_pass = False
        for ir in new_result.image_results:
            if ir.status == "ERROR" or ir.metric is None:
                had_error = had_error or ir.status == "ERROR"
                continue
            if ir.metric <= metric_threshold:
                ir.status = "PASS"
                ir.reason = None if ir.metric == 0 else f"Metric {ir.metric} within threshold {metric_threshold}"
                any_pass = True
            else:
                ir.status = "FAIL"
                ir.reason = "Metric: " + str(ir.metric)
                any_fail = True
        if had_error:
            new_result.result = "ERROR"
        elif any_fail:
            new_result.result = "FAIL"
        elif any_pass or not new_result.image_results:
            new_result.result = "PASS"
        new_result.expected = new_result.expected_result == new_result.result
        new_result.color = new_result.possible_result_colors[new_result.possible_results.index(new_result.result)]
        return new_result


# ---------------------------------------------------------------------------
# Common per-simulation task base
# ---------------------------------------------------------------------------

class ModuleImageTaskBase(Task):
    """Base task: launch one simulation in Qtenv-with-MCP, capture images.

    Subclasses override :py:meth:`_handle_image` to decide what to do
    with each captured PNG (write to output dir, compare against
    baseline, etc.) and to assemble the final task result.
    """

    def __init__(self, simulation_config=None, run_number=0, mode="release",
                 module_path_filter=None, exclude_module_path_filter=None,
                 module_type_filter=None, exclude_module_type_filter=None,
                 group_by="path", area="all_elements", margin=5,
                 startup_timeout=30.0, build=None,
                 name="module image capture", task_result_class=ModuleImageCaptureTaskResult,
                 **kwargs):
        super().__init__(name=name, task_result_class=task_result_class, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.simulation_config = simulation_config
        self.run_number = run_number
        self.mode = mode
        self.module_path_filter = module_path_filter
        self.exclude_module_path_filter = exclude_module_path_filter
        self.module_type_filter = module_type_filter
        self.exclude_module_type_filter = exclude_module_type_filter
        self.group_by = group_by
        self.area = area
        self.margin = margin
        self.startup_timeout = startup_timeout
        self.build = build if build is not None else get_default_build_argument()
        self.mcp_port = None

    def get_parameters_string(self, **kwargs):
        sc = self.simulation_config
        s = sc.working_directory
        if sc.ini_file != "omnetpp.ini":
            s += " -f " + sc.ini_file
        if sc.config != "General":
            s += " -c " + sc.config
        if self.run_number != 0:
            s += " -r " + str(self.run_number)
        return s

    def _spawn(self):
        sc = self.simulation_config
        sp = sc.simulation_project
        if self.mcp_port is None:
            raise RuntimeError("mcp_port has not been preassigned for this task")
        executable = sp.get_executable(mode=self.mode)
        default_args = sp.get_default_args()
        mcp_address = f"localhost:{self.mcp_port}"
        # Use a dedicated result dir so we don't pollute the project's results/.
        result_dir = tempfile.mkdtemp(prefix="opp_module_image_")
        args = [
            executable, *default_args,
            "-u", "Qtenv",
            "--mcp-server-address", mcp_address,
            "-f", sc.ini_file,
            "-c", sc.config,
            "-r", str(self.run_number),
            "--result-dir", result_dir,
        ]
        env = sp.get_env()
        env["QT_QPA_PLATFORM"] = "offscreen"
        cwd = sp.get_full_path(sc.working_directory)
        _logger.debug(f"Spawning Qtenv MCP simulation: {' '.join(args)}")
        process = subprocess.Popen(
            args, cwd=cwd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        return process, result_dir

    def _teardown(self, process, result_dir, client):
        # 1. Polite stop
        if client is not None:
            try:
                client.request_stop_simulation()
            except Exception as e:
                _logger.debug(f"request_stop_simulation failed: {e}")
            try:
                client.close()
            except Exception as e:
                _logger.debug(f"MCP client close failed: {e}")
        # 2. Terminate
        if process.poll() is None:
            try:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            except Exception as e:
                _logger.debug(f"subprocess teardown failed: {e}")
        # 3. Clean up the throwaway result-dir
        if result_dir and os.path.isdir(result_dir):
            try:
                shutil.rmtree(result_dir, ignore_errors=True)
            except Exception:
                pass

    def _capture_all(self):
        """Launch the sim, capture every matching module image, return a list
        of ``(group_key, module_path, ned_type, png_bytes)``.

        Raises on any failure; caller wraps in a task result.
        """
        process, result_dir = self._spawn()
        client = None
        try:
            url = f"http://127.0.0.1:{self.mcp_port}/mcp"
            client = wait_for_mcp_ready(url, total_timeout=self.startup_timeout)
            # Sanity-check the state: events haven't started yet.
            state = client.get_simulation_state()
            if state.get("eventNumber", 0) != 0:
                _logger.debug(f"unexpected eventNumber at startup: {state}")
            if not state.get("networkName"):
                raise RuntimeError("Network was not set up by Qtenv before MCP became ready")
            # Enumerate compound modules.
            topology = client.get_network_topology(max_depth=100)
            all_modules = _walk_compound_modules(topology)
            groups = _filter_and_group(
                all_modules,
                self.module_path_filter, self.exclude_module_path_filter,
                self.module_type_filter, self.exclude_module_type_filter,
                self.group_by,
            )
            captured = []
            for group_key, module_path, ned_type in groups:
                # The MCP get_canvas_image tool expects the system-module's
                # path expressed as "<root>" with the top-level module omitted.
                # The first compound module IS the system module; for it,
                # full_path == "Network" (the network name).  Reuse the
                # full_path; the server resolves it correctly either way.
                mcp_path = module_path
                try:
                    png = client.get_canvas_image(mcp_path, area=self.area, margin=self.margin)
                    captured.append((group_key, module_path, ned_type, png))
                except Exception as e:
                    captured.append((group_key, module_path, ned_type, e))
            return captured, None
        except Exception as e:
            return [], e
        finally:
            self._teardown(process, result_dir, client)

    def get_expected_result(self):
        return "DONE"


# ---------------------------------------------------------------------------
# Capture task
# ---------------------------------------------------------------------------

class ModuleImageCaptureTask(ModuleImageTaskBase):
    def __init__(self, output_dir=None,
                 name="module image capture",
                 task_result_class=ModuleImageCaptureTaskResult, **kwargs):
        super().__init__(name=name, task_result_class=task_result_class, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        if output_dir is None:
            raise ValueError("ModuleImageCaptureTask requires an output_dir")
        self.output_dir = output_dir

    def run_protected(self, **kwargs):
        sc = self.simulation_config
        os.makedirs(self.output_dir, exist_ok=True)
        captured, error = self._capture_all()
        image_results = []
        for group_key, module_path, ned_type, payload in captured:
            filename = _compose_image_filename(sc.working_directory, sc.config,
                                               self.run_number, group_key)
            full = os.path.join(self.output_dir, filename)
            if isinstance(payload, Exception):
                image_results.append(ModuleImageResult(
                    group_key, module_path, ned_type, filename,
                    status="ERROR", reason=str(payload)))
                continue
            try:
                with open(full, "wb") as f:
                    f.write(payload)
                image_results.append(ModuleImageResult(
                    group_key, module_path, ned_type, filename, status="WRITTEN"))
            except Exception as e:
                image_results.append(ModuleImageResult(
                    group_key, module_path, ned_type, filename,
                    status="ERROR", reason=str(e)))
        if error is not None:
            return self.task_result_class(
                task=self, result="ERROR", reason=str(error),
                image_results=image_results)
        any_error = any(ir.status == "ERROR" for ir in image_results)
        if any_error:
            return self.task_result_class(
                task=self, result="ERROR",
                reason="One or more module images could not be captured",
                image_results=image_results)
        return self.task_result_class(task=self, result="DONE", image_results=image_results)


# ---------------------------------------------------------------------------
# Update task — compare new image to existing baseline, INSERT/KEEP/UPDATE
# ---------------------------------------------------------------------------

class ModuleImageUpdateTask(ModuleImageTaskBase):
    def __init__(self, output_dir=None,
                 name="module image update",
                 task_result_class=ModuleImageUpdateTaskResult, **kwargs):
        super().__init__(name=name, task_result_class=task_result_class, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        if output_dir is None:
            raise ValueError("ModuleImageUpdateTask requires an output_dir")
        self.output_dir = output_dir

    def run_protected(self, keep_images=True, **kwargs):
        sc = self.simulation_config
        os.makedirs(self.output_dir, exist_ok=True)
        captured, error = self._capture_all()
        image_results = []
        for group_key, module_path, ned_type, payload in captured:
            filename = _compose_image_filename(sc.working_directory, sc.config,
                                               self.run_number, group_key)
            full = os.path.join(self.output_dir, filename)
            old_full = re.sub(r"\.png$", "-old.png", full)
            diff_full = re.sub(r"\.png$", "-diff.png", full)
            # Remove any stale diff/old sidecar from a previous run.
            for sidecar in (diff_full, old_full):
                if os.path.exists(sidecar):
                    try:
                        os.remove(sidecar)
                    except OSError:
                        pass
            if isinstance(payload, Exception):
                image_results.append(ModuleImageResult(
                    group_key, module_path, ned_type, filename,
                    status="ERROR", reason=str(payload)))
                continue
            if not os.path.exists(full):
                with open(full, "wb") as f:
                    f.write(payload)
                image_results.append(ModuleImageResult(
                    group_key, module_path, ned_type, filename, status="INSERT"))
                continue
            # Baseline exists — compare bytes first (fast), then RMSE.
            with open(full, "rb") as f:
                old_bytes = f.read()
            if old_bytes == payload:
                image_results.append(ModuleImageResult(
                    group_key, module_path, ned_type, filename, status="KEEP"))
                continue
            # Differ — write new, optionally keep old + diff.
            new_full = re.sub(r"\.png$", "-new.png", full)
            with open(new_full, "wb") as f:
                f.write(payload)
            metric = _try_rmse(full, new_full, diff_full if keep_images else None)
            if keep_images:
                try:
                    os.rename(full, old_full)
                except OSError:
                    pass
            else:
                try:
                    os.remove(full)
                except OSError:
                    pass
            os.rename(new_full, full)
            image_results.append(ModuleImageResult(
                group_key, module_path, ned_type, filename,
                status="UPDATE", metric=metric))
        if error is not None:
            return self.task_result_class(
                task=self, result="ERROR", reason=str(error),
                image_results=image_results)
        # Aggregate verdict.
        if any(ir.status == "ERROR" for ir in image_results):
            agg = "ERROR"
        elif any(ir.status == "UPDATE" for ir in image_results):
            agg = "UPDATE"
        elif any(ir.status == "INSERT" for ir in image_results):
            agg = "INSERT"
        else:
            agg = "KEEP"
        return self.task_result_class(task=self, result=agg, image_results=image_results)


# ---------------------------------------------------------------------------
# Test task — render fresh, compare against baseline, PASS/FAIL
# ---------------------------------------------------------------------------

class ModuleImageTestTask(ModuleImageTaskBase):
    def __init__(self, baseline_dir=None, metric_threshold=0,
                 name="module image test",
                 task_result_class=ModuleImageTestTaskResult, **kwargs):
        super().__init__(name=name, task_result_class=task_result_class, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        if baseline_dir is None:
            raise ValueError("ModuleImageTestTask requires a baseline_dir")
        self.baseline_dir = baseline_dir
        self.metric_threshold = metric_threshold

    def run_protected(self, keep_images=True, **kwargs):
        sc = self.simulation_config
        captured, error = self._capture_all()
        image_results = []
        for group_key, module_path, ned_type, payload in captured:
            filename = _compose_image_filename(sc.working_directory, sc.config,
                                               self.run_number, group_key)
            baseline_path = os.path.join(self.baseline_dir, filename)
            new_path = re.sub(r"\.png$", "-new.png", baseline_path)
            diff_path = re.sub(r"\.png$", "-diff.png", baseline_path)
            # Clean up stale sidecars first.
            for sidecar in (new_path, diff_path):
                if os.path.exists(sidecar):
                    try:
                        os.remove(sidecar)
                    except OSError:
                        pass
            if isinstance(payload, Exception):
                image_results.append(ModuleImageResult(
                    group_key, module_path, ned_type, filename,
                    status="ERROR", reason=str(payload)))
                continue
            if not os.path.exists(baseline_path):
                image_results.append(ModuleImageResult(
                    group_key, module_path, ned_type, filename,
                    status="FAIL", reason="Baseline image not found"))
                continue
            # Write the new image next to the baseline, then RMSE-compare.
            with open(new_path, "wb") as f:
                f.write(payload)
            metric = _try_rmse(baseline_path, new_path, diff_path)
            if metric is None:
                image_results.append(ModuleImageResult(
                    group_key, module_path, ned_type, filename,
                    status="ERROR",
                    reason="Could not compute RMSE (baseline and new image incomparable)"))
                continue
            if metric <= self.metric_threshold:
                if not keep_images:
                    try:
                        os.remove(new_path)
                    except OSError:
                        pass
                # diff is only written by _try_rmse when metric > 0
                status = "PASS"
                reason = None if metric == 0 else f"Metric {metric} within threshold {self.metric_threshold}"
            else:
                status = "FAIL"
                reason = "Metric: " + str(metric)
            image_results.append(ModuleImageResult(
                group_key, module_path, ned_type, filename,
                status=status, reason=reason, metric=metric))
        if error is not None:
            return self.task_result_class(
                task=self, result="ERROR", reason=str(error),
                image_results=image_results)
        # Aggregate verdict.
        if any(ir.status == "ERROR" for ir in image_results):
            agg = "ERROR"
        elif any(ir.status == "FAIL" for ir in image_results):
            agg = "FAIL"
        elif not image_results:
            agg = "SKIP"
        else:
            agg = "PASS"
        reason = None
        if agg == "FAIL":
            fails = [ir for ir in image_results if ir.status == "FAIL"]
            reason = f"{len(fails)}/{len(image_results)} image(s) failed"
        return self.task_result_class(task=self, result=agg, image_results=image_results,
                                      reason=reason)


def _try_rmse(old_path, new_path, diff_path):
    """Compute the RMSE between two PNGs, writing a diff image on non-zero.

    Lazy-imports matplotlib/numpy so the rest of the module remains
    usable without the ``chart`` optional dependency.
    """
    try:
        from opp_repl.test.chart import compute_chart_image_diff
    except ImportError as e:
        raise RuntimeError("matplotlib/numpy are required for module-image tests "
                           "(install with `pip install -e .[chart]`)") from e
    return compute_chart_image_diff(old_path, new_path, diff_file_name=diff_path)


# ---------------------------------------------------------------------------
# Multiple-tasks containers
# ---------------------------------------------------------------------------

class _ModuleImageMultipleTasksMixin:
    """Shared build + port-preassignment behavior for the three containers."""

    def __init__(self, simulation_project=None, mode="release", build=None,
                 build_engine=None, port_range=None, **kwargs):
        super().__init__(**kwargs)
        # Stash on self so run_protected can use them.
        self.simulation_project = simulation_project
        self.mode = mode
        self.build = build if build is not None else get_default_build_argument()
        self.build_engine = build_engine
        self.port_range = port_range

    def build_before_run(self, **kwargs):
        if self.simulation_project is not None:
            self.simulation_project.build(mode=self.mode, build_engine=self.build_engine)

    def run_protected(self, build=None, **kwargs):
        will_build = build if build is not None else self.build
        if will_build:
            self.build_before_run(**kwargs)
        kwargs["build"] = False
        # Re-assign ports on every run (incl. rerun) — old assignments may be stale.
        _assign_mcp_ports(self.tasks, port_range=self.port_range)
        return super().run_protected(**kwargs)


class MultipleModuleImageCaptureTasks(_ModuleImageMultipleTasksMixin, MultipleTasks):
    def __init__(self, name="module image capture",
                 multiple_task_results_class=MultipleModuleImageCaptureTaskResults,
                 **kwargs):
        super().__init__(name=name,
                         multiple_task_results_class=multiple_task_results_class,
                         **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs


class MultipleModuleImageUpdateTasks(_ModuleImageMultipleTasksMixin, MultipleUpdateTasks):
    def __init__(self, name="module image update", **kwargs):
        super().__init__(name=name, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs


class MultipleModuleImageTestTasks(_ModuleImageMultipleTasksMixin, MultipleTestTasks):
    def __init__(self, name="module image test", **kwargs):
        super().__init__(name=name, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs


# ---------------------------------------------------------------------------
# Discovery + top-level user-facing functions
# ---------------------------------------------------------------------------

def _build_capture_tasks(simulation_project, output_dir, task_class, extra_task_kwargs,
                        **kwargs):
    """Common logic: enumerate simulation configs/runs and wrap each as a task."""
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    # Lean on get_simulation_tasks to apply the standard filter parameters
    # (config_filter, working_directory_filter, run_number_filter, etc.).
    placeholder_tasks = get_simulation_tasks(simulation_project=simulation_project, **kwargs)
    tasks = []
    for st in placeholder_tasks.tasks:
        tasks.append(task_class(
            simulation_config=st.simulation_config,
            run_number=st.run_number,
            mode=st.mode,
            output_dir=output_dir,
            **extra_task_kwargs,
        ))
    return tasks, simulation_project


def get_module_image_capture_tasks(simulation_project=None, output_dir=None,
                                   module_path_filter=None,
                                   exclude_module_path_filter=None,
                                   module_type_filter=None,
                                   exclude_module_type_filter=None,
                                   group_by="path", area="all_elements", margin=5,
                                   startup_timeout=30.0, port_range=None,
                                   **kwargs):
    """Build a :class:`MultipleModuleImageCaptureTasks` matching the filters."""
    if output_dir is None:
        raise ValueError("output_dir is required")
    extra = dict(
        module_path_filter=module_path_filter,
        exclude_module_path_filter=exclude_module_path_filter,
        module_type_filter=module_type_filter,
        exclude_module_type_filter=exclude_module_type_filter,
        group_by=group_by, area=area, margin=margin,
        startup_timeout=startup_timeout,
    )
    tasks, simulation_project = _build_capture_tasks(
        simulation_project, output_dir, ModuleImageCaptureTask, extra, **kwargs)
    return MultipleModuleImageCaptureTasks(
        tasks=tasks, simulation_project=simulation_project, port_range=port_range,
        **{k: v for k, v in kwargs.items() if k in ("mode", "build", "build_engine", "concurrent", "scheduler")})


def capture_module_images(**kwargs):
    """Capture one image per compound module from each filtered simulation.

    Parameters:
        simulation_project: project whose simulations to launch.
            Defaults to the current default project.
        output_dir: directory the PNGs are written into (required).
        module_path_filter / exclude_module_path_filter: glob patterns
            matched against each module's full path
            (e.g. ``"**.host[*]"``).
        module_type_filter / exclude_module_type_filter: glob patterns
            matched against each module's fully-qualified NED type
            (e.g. ``"inet.node.inet.StandardHost"``).
        group_by: how to deduplicate images. One of ``"path"``
            (one image per instance, default), ``"type"`` (one image
            per NED type), ``"path_no_indices"`` (collapse ``[N]``
            array suffixes).
        area: ``get_canvas_image`` area parameter — ``"all_elements"``
            (default), ``"module_rectangle"``, or ``"viewport"``.
        margin: pixel margin around the captured area (default 5).
        startup_timeout: seconds to wait for the simulation's MCP
            endpoint to become reachable (default 30).
        port_range: optional ``(low, high)`` tuple bounding the TCP
            ports allocated for the per-sim MCP servers.

    All remaining ``**kwargs`` are forwarded to
    :py:func:`get_simulation_tasks`, so the usual
    ``config_filter`` / ``working_directory_filter`` / ``run_number_filter``
    etc. apply.

    Returns: :class:`MultipleModuleImageCaptureTaskResults` with one
    result per (config, run) and a per-image breakdown on each result's
    ``image_results`` attribute.
    """
    return get_module_image_capture_tasks(**kwargs).run(**kwargs)
capture_module_images.__signature__ = combine_signatures(
    capture_module_images, get_module_image_capture_tasks, get_simulation_tasks)


def get_module_image_update_tasks(simulation_project=None,
                                  module_path_filter=None,
                                  exclude_module_path_filter=None,
                                  module_type_filter=None,
                                  exclude_module_type_filter=None,
                                  group_by="path", area="all_elements", margin=5,
                                  startup_timeout=30.0, port_range=None,
                                  **kwargs):
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    output_dir = simulation_project.get_full_path(simulation_project.module_image_baseline_folder)
    extra = dict(
        module_path_filter=module_path_filter,
        exclude_module_path_filter=exclude_module_path_filter,
        module_type_filter=module_type_filter,
        exclude_module_type_filter=exclude_module_type_filter,
        group_by=group_by, area=area, margin=margin,
        startup_timeout=startup_timeout,
    )
    tasks, simulation_project = _build_capture_tasks(
        simulation_project, output_dir, ModuleImageUpdateTask, extra, **kwargs)
    return MultipleModuleImageUpdateTasks(
        tasks=tasks, simulation_project=simulation_project, port_range=port_range,
        **{k: v for k, v in kwargs.items() if k in ("mode", "build", "build_engine", "concurrent", "scheduler")})


def update_module_image_test_results(**kwargs):
    """Capture into the project's ``module_image_baseline_folder``.

    Like :py:func:`capture_module_images`, but the output directory is
    fixed to ``<simulation_project>/<module_image_baseline_folder>``
    and existing baselines are diffed against the freshly captured
    images:

    - INSERT: no baseline existed → the new image becomes the baseline.
    - KEEP: the bytes match exactly.
    - UPDATE: the bytes differ → the old baseline is renamed to
      ``<name>-old.png``, a ``<name>-diff.png`` is written next to it,
      and the new image takes its place.
    """
    return get_module_image_update_tasks(**kwargs).run(**kwargs)
update_module_image_test_results.__signature__ = combine_signatures(
    update_module_image_test_results, get_module_image_update_tasks, get_simulation_tasks)


def get_module_image_test_tasks(simulation_project=None,
                                baseline_simulation_project=None,
                                metric_threshold=0,
                                module_path_filter=None,
                                exclude_module_path_filter=None,
                                module_type_filter=None,
                                exclude_module_type_filter=None,
                                group_by="path", area="all_elements", margin=5,
                                startup_timeout=30.0, port_range=None,
                                **kwargs):
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    if baseline_simulation_project is None:
        baseline_simulation_project = simulation_project
    baseline_dir = baseline_simulation_project.get_full_path(
        baseline_simulation_project.module_image_baseline_folder)
    extra = dict(
        baseline_dir=baseline_dir,
        metric_threshold=metric_threshold,
        module_path_filter=module_path_filter,
        exclude_module_path_filter=exclude_module_path_filter,
        module_type_filter=module_type_filter,
        exclude_module_type_filter=exclude_module_type_filter,
        group_by=group_by, area=area, margin=margin,
        startup_timeout=startup_timeout,
    )
    # ModuleImageTestTask uses ``baseline_dir`` not ``output_dir``; pass
    # baseline_dir manually via extra dict and use a wrapper builder.
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    placeholder_tasks = get_simulation_tasks(simulation_project=simulation_project, **kwargs)
    tasks = []
    for st in placeholder_tasks.tasks:
        tasks.append(ModuleImageTestTask(
            simulation_config=st.simulation_config,
            run_number=st.run_number,
            mode=st.mode,
            **extra,
        ))
    return MultipleModuleImageTestTasks(
        tasks=tasks, simulation_project=simulation_project, port_range=port_range,
        **{k: v for k, v in kwargs.items() if k in ("mode", "build", "build_engine", "concurrent", "scheduler")})


def run_module_image_tests(**kwargs):
    """Compare freshly rendered module images against the baseline.

    Returns :class:`MultipleTestTaskResults` with PASS/FAIL/SKIP/ERROR
    per simulation.  Each task result also carries an ``image_results``
    list with the per-module RMSE metric and verdict.

    Set ``baseline_simulation_project`` to compare against a different
    project's baseline (e.g. a known-good branch checked out in a
    sibling directory).
    """
    return get_module_image_test_tasks(**kwargs).run(**kwargs)
run_module_image_tests.__signature__ = combine_signatures(
    run_module_image_tests, get_module_image_test_tasks, get_simulation_tasks)
