# Project Descriptor Files (`.opp`)

Projects are described by `.opp` files — small Python expressions that
define either an `OmnetppProject` or a `SimulationProject`.  They use a
restricted syntax: a single constructor call with keyword-only literal
arguments (strings, numbers, booleans, lists, dicts, `None`).

## Path Resolution

The parameters `root_folder`, `overlay_build_root`, and `opp_env_workspace` are
filesystem paths.  When specified as **relative paths**, they are resolved
relative to the directory containing the `.opp` file — not relative to the
current working directory.  Absolute paths are used as-is.

This means `root_folder="."` always refers to the directory where the `.opp`
file lives, regardless of where the tool is invoked from.

Other folder parameters (`bin_folder`, `ned_folders`, `ini_file_folders`,
etc.) are always relative to the project's root and are **not** affected
by this resolution.

## Locating the Project Root

Both `OmnetppProject` and `SimulationProject` support multiple ways to
specify the project root directory.  They are tried in the following order:

1. **`root_folder`** — an explicit path.  When relative, it is resolved
   against the `.opp` file's directory at load time.
2. **`root_folder_environment_variable`** — the value of the named OS
   environment variable is used as the root.  `SimulationProject`
   additionally supports
   **`root_folder_environment_variable_relative_folder`** (default `"."`),
   which is appended to the environment variable value to form the final
   project root.  This is useful for projects that live as subdirectories
   under a common root (e.g. OMNeT++ samples under
   `$__omnetpp_root_dir/samples/`).

The recommended approach for `.opp` files that live inside the project
tree is `root_folder="."`.

## OmnetppProject

Describes an OMNeT++ installation.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | Human-readable name for this OMNeT++ installation |
| `version` | `str` | Version string (e.g. `"6.1"`) |
| `root_folder_environment_variable` | `str` | OS environment variable pointing to the root folder (default: `"__omnetpp_root_dir"`) |
| `root_folder` | `str` | Explicit root folder path (overrides `root_folder_environment_variable`); relative paths are resolved against the `.opp` file's directory |
| `overlay_name` | `str` | Enable overlay builds via fuse-overlayfs with this name |
| `overlay_build_root` | `str` | Override the overlay build root directory; relative paths are resolved against the `.opp` file's directory |
| `opp_env_workspace` | `str` | Path to opp_env workspace; relative paths are resolved against the `.opp` file's directory |
| `opp_env_project` | `str` | opp_env project identifier (e.g. `"omnetpp-6.3.0"`) |

## SimulationProject

Describes a simulation project (INET, Simu5G, OMNeT++ samples, etc.).

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | *(required)* | Human-readable project name |
| `version` | `str` | `None` | Version string |
| `omnetpp_project` | `str` | `None` | Name of the `OmnetppProject` to use (resolved lazily) |
| `root_folder` | `str` | `None` | Root folder; relative paths are resolved against the `.opp` file's directory |
| `root_folder_environment_variable` | `str` | `None` | OS environment variable for the root folder (fallback when `root_folder` is not set) |
| `root_folder_environment_variable_relative_folder` | `str` | `"."` | Project directory relative to the env var value |
| `bin_folder` | `str` | `"."` | Binary output directory relative to root |
| `library_folder` | `str` | `"."` | Library output directory relative to root |
| `build_types` | `list[str]` | `["dynamic library"]` | Build output types: `"executable"`, `"dynamic library"`, `"static library"` |
| `executables` | `list[str]` | `None` | Executable names to build |
| `dynamic_libraries` | `list[str]` | `None` | Dynamic library names to build |
| `ned_folders` | `list[str]` | `["."]` | Directories containing NED files (relative to root) |
| `ned_exclusions` | `list[str]` | `[]` | Excluded NED packages |
| `ini_file_folders` | `list[str]` | `["."]` | Directories containing INI files (relative to root) |
| `used_projects` | `list[str]` | `[]` | Names of dependent simulation projects |
| `media_folder` | `str` | `"."` | Directory for chart test baseline images (relative to root) |
| `statistics_folder` | `str` | `"."` | Directory for statistical test baseline results (relative to root) |
| `fingerprint_store` | `str` | `"fingerprint.json"` | Path to the JSON fingerprint store (relative to root) |
| `speed_store` | `str` | `"speed.json"` | Path to the JSON speed measurement store (relative to root) |
| `overlay_name` | `str` | `None` | Enable overlay builds with this name |
| `overlay_build_root` | `str` | `None` | Override overlay build root; relative paths are resolved against the `.opp` file's directory |
| `opp_env_workspace` | `str` | `None` | Path to opp_env workspace; relative paths are resolved against the `.opp` file's directory |
| `opp_env_project` | `str` | `None` | opp_env project identifier (e.g. `"inet-4.6.0"`) |
| `github_owner` | `str` | `None` | GitHub owner/organization for workflow dispatch |
| `github_repository` | `str` | `None` | GitHub repository name for workflow dispatch |
| `github_workflows` | `list[str]` | `None` | GitHub Actions workflow file names (e.g. `["fingerprint-tests.yml"]`) |

## Examples

### OMNeT++ installation with relative path

The `.opp` file lives in the OMNeT++ root directory.  `root_folder="."` is
resolved to that directory at load time.

```python
# ~/workspace/omnetpp/omnetpp.opp
OmnetppProject(
    name="omnetpp",
    root_folder=".",
)
```

### OMNeT++ installation with environment variable

When the root is not known at authoring time (e.g. shared `.opp` files),
use an environment variable instead.

```python
OmnetppProject(
    name="omnetpp",
    root_folder_environment_variable="OMNETPP_ROOT",
)
```

### OMNeT++ installation with absolute path

Useful when the `.opp` file is not stored alongside the installation, e.g.
for a system-wide OMNeT++ in `/opt`.

```python
OmnetppProject(
    name="omnetpp",
    root_folder="/opt/omnetpp-7.0",
)
```

### Standalone OMNeT++ sample (executable, with relative path)

The `.opp` file is inside the sample directory.  `root_folder="."` makes
the sample its own self-contained project.

```python
# ~/workspace/omnetpp/samples/aloha/aloha.opp
SimulationProject(
    name="aloha",
    root_folder=".",
    omnetpp_project="omnetpp",
    build_types=["executable"],
    ned_folders=["."],
    ini_file_folders=["."],
)
```

### OMNeT++ sample (executable, with environment variable)

When the `.opp` file does not live inside the project tree,
`root_folder_environment_variable` with
`root_folder_environment_variable_relative_folder` locates the sample
under the OMNeT++ root.

```python
SimulationProject(
    name="aloha",
    root_folder_environment_variable="__omnetpp_root_dir",
    root_folder_environment_variable_relative_folder="samples/aloha",
    omnetpp_project="omnetpp",
    build_types=["executable"],
    ned_folders=["."],
    ini_file_folders=["."],
)
```

### INET Framework (dynamic library)

A full-featured project descriptor for INET.  Note the separate
`library_folder` and `bin_folder` (INET builds its shared library under
`src/` and its binaries under `bin/`), and the test-related stores that
point to non-default locations.

```python
# ~/workspace/inet/inet.opp
SimulationProject(
    name="inet",
    root_folder=".",
    library_folder="src",
    bin_folder="bin",
    dynamic_libraries=["INET"],
    ned_folders=["src", "examples", "showcases", "tutorials", "tests/networks"],
    ini_file_folders=["examples", "showcases", "tutorials", "tests/fingerprint"],
    media_folder="doc/media",
    fingerprint_store="tests/fingerprint/store.json",
    speed_store="tests/speed/store.json",
    github_owner="inet-framework",
    github_repository="inet",
    github_workflows=[
        "fingerprint-tests.yml",
        "statistical-tests.yml",
        "chart-tests.yml",
    ],
)
```

### Overlay build (INET sources + specific OMNeT++ version)

The `overlay_name` triggers a fuse-overlayfs mount so that builds do not
modify the original source tree.  `root_folder="."` tells the overlay
where to find the source files.

```python
# ~/workspace/inet/inet+omnetpp.opp
SimulationProject(
    name="inet+omnetpp",
    root_folder=".",
    omnetpp_project="omnetpp",
    overlay_name="inet+omnetpp",
    library_folder="src",
    bin_folder="bin",
    build_types=["dynamic library"],
    dynamic_libraries=["INET"],
    ned_folders=["src", "examples", "showcases", "tutorials", "tests/networks"],
    ini_file_folders=["examples"],
)
```

### Simu5G (depends on INET)

Simu5G builds on top of INET.  The `used_projects=["inet"]` parameter
tells opp_repl to build INET first and to include INET's NED and library
paths when running simulations.

```python
# ~/workspace/simu5g/simu5g.opp
SimulationProject(
    name="simu5g",
    root_folder=".",
    omnetpp_project="omnetpp",
    library_folder="src",
    bin_folder="bin",
    build_types=["dynamic library"],
    dynamic_libraries=["simu5g"],
    used_projects=["inet"],
    ned_folders=["src", "simulations"],
    ini_file_folders=["simulations"],
)
```

### opp_env-managed OMNeT++ installation

For OMNeT++ versions installed via the `opp_env` tool, `opp_env_workspace`
and `opp_env_project` route all build and run commands through
`opp_env run`.

```python
# ~/opp_env/omnetpp-6.3.0/omnetpp.opp
OmnetppProject(
    name="omnetpp-6.3.0-opp_env",
    root_folder=".",
    opp_env_workspace="/home/user/opp_env",
    opp_env_project="omnetpp-6.3.0",
)
```

### opp_env-managed INET

Same pattern for a simulation project managed by opp_env.  The
`omnetpp_project` must point to an opp_env-managed OMNeT++ project so
that the environment is set up consistently.

```python
# ~/opp_env/inet-4.6.0/inet-4.6.0.opp
SimulationProject(
    name="inet-4.6.0-opp_env",
    root_folder=".",
    omnetpp_project="omnetpp-6.3.0-opp_env",
    opp_env_project="inet-4.6.0",
    opp_env_workspace="/home/user/opp_env",
    library_folder="src",
    bin_folder="bin",
    build_types=["dynamic library"],
    dynamic_libraries=["INET"],
    ned_folders=["src", "examples", "showcases", "tutorials", "tests/networks"],
    ini_file_folders=["examples"],
)
```
