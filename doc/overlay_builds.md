# Overlay Builds

Overlay builds use `fuse-overlayfs` to create a writable layer on top
of a read-only source tree, allowing out-of-tree builds without
modifying the original checkout.

## Why overlays?

Building a simulation project normally writes object files, libraries,
and generated code directly into the source tree.  This is problematic
when you want to:

- **Keep the source tree clean** — no build artifacts appear in `git
  status`, no risk of accidentally committing generated files.
- **Build the same source with different OMNeT++ versions** — each overlay
  gets its own compiled binaries while sharing the same source files.
- **Run multiple build modes in parallel** — e.g. a `release` overlay and
  a `sanitize` overlay from the same checkout, without `make clean`
  between them.
- **Work with read-only checkouts** — useful in CI or when the source
  lives on a read-only filesystem.

## How they work

An overlay combines a **lower directory** (the original source tree,
read-only) with an **upper directory** (writable, stores all changes).
The kernel (via `fuse-overlayfs`) presents a **merged directory** where
the two layers appear as a single writable tree:

```
lower (source tree)  ──┐
                       ├──▶  merged (appears writable)
upper (build output) ──┘
```

Any file that is read but not modified comes from the lower directory.
Any file that is created or modified is written to the upper directory.
The original source tree is never touched.

## Directory layout

All overlay data is stored under the **build root**, which defaults to
`~/.omnetpp/build` (override with the `OPP_BUILD_ROOT` environment
variable or the `overlay_build_root` parameter):

```
~/.omnetpp/build/
  <overlay_name>/
    upper/    ← writable layer (object files, binaries, generated code)
    work/     ← internal bookkeeping for fuse-overlayfs
    merged/   ← the mount point where lower + upper are combined
```

Each project with `overlay_name` set gets its own subdirectory.

## Configuring overlays

Set `overlay_name` in the project's `.opp` file:

```python
SimulationProject(
    name="inet",
    root_folder=".",
    omnetpp_project="omnetpp",
    overlay_name="inet-release",
    ...
)
```

Optionally set `overlay_build_root` to store build artifacts somewhere
other than `~/.omnetpp/build`:

```python
SimulationProject(
    ...
    overlay_name="inet-release",
    overlay_build_root="/tmp/builds",
)
```

Both `OmnetppProject` and `SimulationProject` support `overlay_name` and
`overlay_build_root` as constructor parameters (and `.opp` file entries).

### Multiple overlays for the same source

To build the same project against different OMNeT++ versions, create
separate `.opp` files with distinct overlay names:

```python
# inet-release.opp — builds against the default OMNeT++
SimulationProject(
    name="inet",
    overlay_name="inet-release",
    omnetpp_project="omnetpp",
    ...
)

# inet-sanitize.opp — builds against an OMNeT++ sanitizer build
SimulationProject(
    name="inet",
    overlay_name="inet-sanitize",
    omnetpp_project="omnetpp-sanitize",
    ...
)
```

## Lifecycle

The overlay is managed automatically:

- **Mounting** — `ensure_mounted()` is called before any build or
  simulation run.  If the overlay is already mounted, this is a no-op.
  The directories are created on first use.
- **Building** — `build()` compiles into the merged directory, so all
  generated files land in the upper layer.
- **Running** — simulations see the full merged tree (source + build
  output) as their working environment.
- **Cleaning** — `clean()` on an overlay project unmounts and removes the
  upper and work directories, effectively discarding all build artifacts.

You can also manage overlays manually:

```python
project.ensure_mounted()   # mount if not already
project.is_mounted()       # check mount status
project.unmount()          # unmount (keeps upper layer on disk)
project.clean()            # unmount and delete upper/work dirs
```

## Housekeeping

```python
from opp_repl.simulation.overlay import *

list_overlays()          # list overlay names under the build root
cleanup_overlays()       # unmount all overlays
clear_build_root()       # unmount and remove the entire build root
```

- `list_overlays()` returns overlay names that have directories under the
  build root.
- `cleanup_overlays()` unmounts all overlays but keeps the data on disk
  (upper layers are preserved, so re-mounting is cheap).
- `clear_build_root()` unmounts everything and deletes the build root
  directory entirely, freeing all disk space used by overlay builds.

## Pre-mounting for sandboxed execution

When running inside `opp_sandbox`, the sandbox restricts the
permissions needed by `fuse-overlayfs` to mount overlays.  The solution
is to mount overlays **before** entering the sandbox using the
`opp_mount` command, and unmount them afterwards with `opp_unmount`.

### `opp_mount`

```bash
opp_mount "/home/user/workspace/opp/*.opp"
```

Parses the given `.opp` files (glob patterns are supported), finds
projects that have `overlay_name` set, and mounts each overlay.
Already-mounted overlays are skipped.

### `opp_unmount`

```bash
opp_unmount "/home/user/workspace/opp/*.opp"   # unmount specific overlays
opp_unmount                                     # unmount all overlays
```

Unmounts overlays.  When called with `.opp` file arguments, only the
matching overlays are unmounted.  When called without arguments, all
active overlays under the build root are unmounted.

### Sandboxed workflow

```bash
# 1. Mount overlays outside the sandbox
opp_mount "/home/user/workspace/opp/*.opp"

# 2. Run the sandbox — overlays are already mounted and visible
#    via ~/.omnetpp/build which is writable inside the sandbox
opp_sandbox -w ~/workspace -- opp_repl --load "/home/user/workspace/opp/*.opp"

# 3. Clean up after the sandbox exits
opp_unmount
```

Inside the sandbox, `opp_repl` detects the pre-existing mounts (via
`/proc/mounts`) and skips the `fuse-overlayfs` call entirely, so no
extra capabilities are needed.

## Prerequisites

Overlay builds require `fuse-overlayfs` and `fusermount` to be installed
and available on `PATH`.  On Debian/Ubuntu:

```bash
sudo apt install fuse-overlayfs
```

No root privileges are needed at runtime — `fuse-overlayfs` runs in
user space.
