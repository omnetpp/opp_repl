# Module-Image Tests

Module-image tests detect visual regressions in network module
diagrams.  Each filtered simulation is launched in **Qtenv with its
MCP server enabled**, and a PNG image of every compound module
matching the include/exclude filters is captured at simulation time
``t=0`` (immediately after the network has been built, before any
event runs).  Images are compared against baselines stored in the
project's ``module_image_baseline_folder``.

This is the visual companion to chart tests
(see [chart_tests.md](chart_tests.md)), but for the network topology
itself.

## Prerequisites

Module-image tests require the **`mcp`** optional dependency group:

```bash
pip install -e ".[mcp]"
```

The `run_module_image_tests` comparison step additionally needs
**matplotlib** and **numpy**, i.e. the `chart` group:

```bash
pip install -e ".[mcp,chart]"
```

OMNeT++ must be built with MCP server support
(``WITH_MCP_SERVER`` — the default in recent ``omnetpp-ai-preview``
builds).  Qtenv rendering uses Qt's offscreen platform plugin
(``QT_QPA_PLATFORM=offscreen``) so no X server / Wayland session is
required.

## How it works

For each (simulation config, run number) that passes the filter:

1. A free TCP port is preassigned by the top-level function (so
   concurrent tasks never compete for the same port).
2. The simulation is spawned in Qtenv with
   ``--mcp-server-address localhost:<port>`` and
   ``QT_QPA_PLATFORM=offscreen``.
3. Python connects to the MCP endpoint via the official ``mcp`` SDK,
   waits until the network has been built (``networkName`` set,
   ``eventNumber == 0``).
4. ``get_network_topology`` is called and the result is walked to
   collect every node with at least one submodule — these are the
   "compound modules" eligible for capture.
5. The include/exclude path and type filters are applied; the
   surviving modules are grouped by ``group_by`` (see below).
6. For each group, ``get_canvas_image`` returns a base64-encoded PNG
   which is decoded and written to disk.
7. The simulation is asked to stop (``request_stop_simulation``),
   the MCP session is closed, and the subprocess is terminated.

## Filters and grouping

Two pairs of glob-pattern filter parameters control which modules are
captured:

- ``module_path_filter`` / ``exclude_module_path_filter`` — matched
  against each module's full path (e.g. ``"**.host[*]"``,
  ``"Network.router*"``).
- ``module_type_filter`` / ``exclude_module_type_filter`` — matched
  against each module's fully-qualified NED type
  (e.g. ``"inet.node.inet.StandardHost"``, ``"inet.**"``).

A module is captured iff it passes **both** filter pairs.

Grouping (``group_by``) controls how many images are produced when the
same module recurs in many places:

- ``"path"`` (default) — one image per full path.
- ``"type"`` — one image per distinct NED type.
- ``"path_no_indices"`` — collapse ``[N]`` array suffixes so
  ``host[0]``…``host[99]`` share a single image (the first encountered
  instance is the representative).

## Image filenames

```
<working_directory>__<config>__r<run>__<group_key>.png
```

where the components are joined by ``__`` and ``/`` is replaced by
``_`` in each component.  Examples:

```
examples_ethernet_simple__SimpleNet__r0__SimpleNet.png
examples_ethernet_simple__SimpleNet__r0__SimpleNet.client.png
samples_fifo__Fifo1__r0__Fifo1.png
```

## Python API

### Ad-hoc capture

```python
capture_module_images(
    simulation_project=inet_project,
    output_dir="/tmp/snap",
    module_type_filter="inet.**",
    group_by="type",
)
```

Returns a ``MultipleModuleImageCaptureTaskResults``.  Each per-task
result has a ``result`` of ``DONE`` / ``ERROR`` / ``SKIP`` / ``CANCEL``
and an ``image_results`` list with one entry per module-group
containing ``status`` (``WRITTEN`` / ``ERROR``), ``filename``,
``module_path``, ``ned_type``.

### Storing baseline images

```python
update_module_image_test_results(simulation_project=inet_project)
```

Writes the captures into
``<inet_project>/<module_image_baseline_folder>``.  When a baseline
already exists, the new image is compared to it byte-wise:

- **INSERT** — no baseline existed; the new image becomes the
  baseline.
- **KEEP** — the bytes match exactly.
- **UPDATE** — the bytes differ; the old baseline is renamed to
  ``<name>-old.png``, a ``<name>-diff.png`` is written next to it
  (using the chart-test RMSE pipeline), and the new image takes its
  place.

### Running module-image tests

```python
r = run_module_image_tests(simulation_project=inet_project)

# Filter to a specific area of the project
run_module_image_tests(simulation_project=inet_project,
                       working_directory_filter="examples/ethernet")

# Re-run only the failures
r.get_fail_results().rerun()

# Compare against a different baseline (e.g. a baseline branch)
run_module_image_tests(simulation_project=inet_project,
                       baseline_simulation_project=inet_baseline_project)
```

The aggregate per-simulation result is ``PASS`` / ``FAIL`` / ``SKIP``
/ ``ERROR``.  Each per-task result's ``image_results`` list contains
one ``ModuleImageResult`` per module group with:

- ``status`` — ``PASS`` / ``FAIL`` / ``ERROR``
- ``metric`` — RMSE between baseline and new image (0 = pixel
  identical), or ``None`` when the comparison could not run
- ``reason`` — explanation on non-PASS

When a per-module test fails, ``<name>-new.png`` and
``<name>-diff.png`` are written next to the baseline file for
inspection.

### Changing the threshold without re-rendering

```python
r0 = r.results[0]
r0_recheck = r0.recheck(metric_threshold=0.05)
```

``recheck`` reuses the per-image metrics stored on the result, so the
verdict can move from FAIL → PASS (or vice versa) without launching
any simulation.

## Command Line

```bash
opp_capture_module_images --load /path/to/inet.opp -p inet \
    --working-directory-filter examples/ethernet \
    --module-type-filter 'inet.**' \
    --output-dir /tmp/snap

opp_update_module_image_test_results --load /path/to/inet.opp -p inet \
    --working-directory-filter examples/ethernet

opp_run_module_image_tests --load /path/to/inet.opp -p inet \
    --working-directory-filter examples/ethernet
```

Use ``--baseline-simulation-project <name>`` with
``opp_run_module_image_tests`` to compare against a different
project's baseline.

## Baseline location

The baseline folder is configured per-project via the
``module_image_baseline_folder`` parameter of ``SimulationProject``
(default ``"media/module_images"``).  All baseline PNGs live in a
single flat directory; uniqueness is guaranteed by the filename scheme
above.
