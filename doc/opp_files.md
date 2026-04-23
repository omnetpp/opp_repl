# Project Descriptor Files (`.opp`)

Projects are described by `.opp` files — small Python expressions that
define either an `OmnetppProject` or a `SimulationProject`.  They use a
restricted syntax: a single constructor call with keyword-only literal
arguments (strings, numbers, booleans, lists, dicts, `None`).

## OmnetppProject

Describes an OMNeT++ installation.

```python
OmnetppProject(
    name="omnetpp",
)
```

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | Human-readable name for this OMNeT++ installation |
| `environment_variable` | `str` | OS environment variable pointing to the root folder (default: `"__omnetpp_root_dir"`) |
| `root_folder` | `str` | Explicit root folder path (overrides `environment_variable`) |
| `overlay_key` | `str` | Enable overlay builds via fuse-overlayfs with this key |
| `build_root` | `str` | Override the overlay build root directory |
| `opp_env_workspace` | `str` | Path to opp_env workspace (for opp_env-managed installations) |
| `opp_env_project` | `str` | opp_env project identifier (e.g. `"omnetpp-6.3.0"`) |

## SimulationProject

Describes a simulation project (INET, Simu5G, OMNeT++ samples, etc.).

```python
SimulationProject(
    name="fifo",
    omnetpp_project="omnetpp",
    build_types=["executable"],
    ned_folders=["."],
    ini_file_folders=["."],
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | *(required)* | Human-readable project name |
| `version` | `str` | `None` | Version string |
| `omnetpp_project` | `str` | `None` | Name of the `OmnetppProject` to use (resolved lazily) |
| `root_folder` | `str` | auto | Root folder (auto-set to the `.opp` file's directory) |
| `folder` | `str` | `"."` | Project directory relative to root |
| `bin_folder` | `str` | `"."` | Binary output directory relative to root |
| `library_folder` | `str` | `"."` | Library output directory relative to root |
| `build_types` | `list[str]` | `["dynamic library"]` | Build output types: `"executable"`, `"dynamic library"`, `"static library"` |
| `executables` | `list[str]` | `None` | Executable names to build |
| `dynamic_libraries` | `list[str]` | `None` | Dynamic library names to build |
| `ned_folders` | `list[str]` | `["."]` | Directories containing NED files |
| `ned_exclusions` | `list[str]` | `[]` | Excluded NED packages |
| `ini_file_folders` | `list[str]` | `["."]` | Directories containing INI files |
| `used_projects` | `list[str]` | `[]` | Names of dependent simulation projects |
| `media_folder` | `str` | `"."` | Directory for chart test baseline images |
| `statistics_folder` | `str` | `"."` | Directory for statistical test baseline results |
| `fingerprint_store` | `str` | `"fingerprint.json"` | Path to the JSON fingerprint store |
| `speed_store` | `str` | `"speed.json"` | Path to the JSON speed measurement store |
| `overlay_key` | `str` | `None` | Enable overlay builds with this key |
| `build_root` | `str` | `None` | Override overlay build root |
| `opp_env_workspace` | `str` | `None` | Path to opp_env workspace |
| `opp_env_project` | `str` | `None` | opp_env project identifier (e.g. `"inet-4.6.0"`) |
| `github_owner` | `str` | `None` | GitHub owner/organization for workflow dispatch |
| `github_repository` | `str` | `None` | GitHub repository name for workflow dispatch |
| `github_workflows` | `list[str]` | `None` | GitHub Actions workflow file names (e.g. `["fingerprint-tests.yml"]`) |

## Example `.opp` Files

### Standalone OMNeT++ sample (executable)

```python
# ~/workspace/omnetpp/samples/aloha/aloha.opp
SimulationProject(
    name="aloha",
    omnetpp_project="omnetpp",
    build_types=["executable"],
    ned_folders=["."],
    ini_file_folders=["."],
)
```

### INET Framework (dynamic library)

```python
# ~/workspace/inet/inet.opp
SimulationProject(
    name="inet",
    library_folder="src",
    bin_folder="bin",
    build_types=["dynamic library"],
    dynamic_libraries=["INET"],
    ned_folders=["src", "examples", "showcases", "tutorials", "tests/networks"],
    ini_file_folders=["examples", "showcases", "tutorials", "tests/fingerprint"],
    media_folder="doc/media",
    statistics_folder="statistics",
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

### INET with explicit OMNeT++ and overlay builds

```python
# ~/workspace/inet/inet+omnetpp.opp
SimulationProject(
    name="inet+omnetpp",
    omnetpp_project="omnetpp",
    overlay_key="inet+omnetpp",
    library_folder="src",
    bin_folder="bin",
    build_types=["dynamic library"],
    dynamic_libraries=["INET"],
    ned_folders=["src", "examples", "showcases", "tutorials", "tests/networks"],
    ini_file_folders=["examples"],
)
```

### Simu5G (depends on INET)

```python
# ~/workspace/simu5g/simu5g.opp
SimulationProject(
    name="simu5g",
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

```python
# ~/opp_env/omnetpp-6.3.0/omnetpp.opp
OmnetppProject(
    name="omnetpp-6.3.0-opp_env",
    opp_env_workspace="/home/user/opp_env",
    opp_env_project="omnetpp-6.3.0",
)
```

### opp_env-managed INET

```python
# ~/opp_env/inet-4.6.0/inet-4.6.0.opp
SimulationProject(
    name="inet-4.6.0-opp_env",
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
