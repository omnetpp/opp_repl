# Build OMNeT++ using per-file opp_repl tasks

Refactor the general task classes in `compile.py` to be parameterized by their degrees of freedom (compiler, flags, input, output, working dir), then create a builder module (`build_omnetpp.py`) that instantiates these tasks with data from `OmnetppProject` / `MakefileIncConfig`.

## Design principle

**Base tasks are general; derived tasks are project-specific.** Base task classes (`CppCompileTask`, `LinkTask`, etc.) hold explicit parameters (compiler, flags, input, output, working_dir). Derived classes (`SimulationProjectCppCompileTask`, `OmnetppProjectCppCompileTask`) wrap their respective project objects and know how to derive the parameters from them.

## Step 1: Refactor `opp_repl/common/compile.py`

### `BuildTask` base class

Replace `simulation_project` with explicit parameters:
- `working_dir` (str) — cwd for subprocess and base for relative paths

Keep `get_input_files()` / `get_output_files()` as overridable methods for up-to-date checking. `run_protected()` uses `working_dir` as cwd.

### `CppCompileTask` (base, general)

Parameters:
- `working_dir`
- `compiler` (list of str, e.g. `["ccache", "g++"]`)
- `cxxflags` (list of str)
- `cflags` (list of str)
- `defines` (list of str)
- `include_dirs` (list of str)
- `input_file` (str)
- `output_file` (str)
- `dependency_file` (str or None)

### `LinkTask` (base, general)

Parameters:
- `working_dir`
- `linker` (list of str)
- `ldflags` (list of str)
- `input_files` (list of str)
- `output_file` (str)
- `libraries` (list of str)
- `library_dirs` (list of str)
- `rpath_dirs` (list of str)
- `type` — `"shared"`, `"static"`, `"executable"`
- For static: `ar`, `ranlib`

### `CopyBinaryTask` (base, general)

Parameters: `working_dir`, `source_file`, `target_file`, `postprocess_command`

### `MsgCompileTask` (base, general)

Refactored to explicit params: `msgc` executable, flags, input .msg, output files.

### New generation task classes

- `YaccTask` — `yacc` executable, flags, input .y, output .cc/.h
- `LexTask` — `lex` executable, flags, input .lex, output .cc/.h
- `PerlGenerateTask` — `perl` executable, script, args, expected outputs
- `MocTask` — `moc` executable, defines, input .h, output .cpp
- `UicTask` — `uic` executable, input .ui, output .h
- `RccTask` — `rcc` executable, input .qrc, output .cpp

### Derived classes for simulation projects (in `build.py`)

- `SimulationProjectCppCompileTask(CppCompileTask)` — takes `simulation_project` + `makefile_inc_config` + `file_path`, derives all base params in `__init__`
- `SimulationProjectLinkTask(LinkTask)` — similarly derives linker params from project
- `SimulationProjectMsgCompileTask(MsgCompileTask)` — derives msgc params from project

These replace the current `CppCompileTask`/`LinkTask`/`MsgCompileTask` usage in `build.py` — same behavior, cleaner factoring.

### Derived classes for OMNeT++ build (in `build_omnetpp.py`)

- `OmnetppProjectCppCompileTask(CppCompileTask)` — takes component info + `makefile_inc_config`, derives compile params
- `OmnetppProjectLinkTask(LinkTask)` — derives link params for OMNeT++ libraries
- `OmnetppProjectCopyBinaryTask(CopyBinaryTask)` — derives source/target from component info

## Step 2: Extend `makefile_vars.py`

Add variables to `_MAKEFILE_INC_VARS`:
`YACC`, `LEX`, `PERL`, `MOC`, `UIC`, `RCC`, `RANLIB`,
`QT_CFLAGS`, `QT_LIBS`, `LIBXML_CFLAGS`, `LIBXML_LIBS`,
`MPI_CFLAGS`, `MPI_LIBS`, `PYTHON_EMBED_CFLAGS`, `PYTHON_EMBED_LDFLAGS`,
`AKAROA_CFLAGS`, `BACKWARD_LDFLAGS`, `PTHREAD_CFLAGS`, `PTHREAD_LIBS`,
`WITH_QTENV`, `WITH_PARSIM`, `WITH_PYTHON`, `WITH_BACKTRACE`,
`PREFER_SQLITE_RESULT_FILES`, `OMNETPP_SRC_DIR`, `OMNETPP_BIN_DIR`, `OMNETPP_OUT_DIR`,
`OMNETPP_IMAGE_PATH`, `SO_LIB_SUFFIX`

Add corresponding `@property` accessors to `MakefileIncConfig`.

## Step 3: Create `opp_repl/simulation/build_omnetpp.py`

### Component data model

A list describing each OMNeT++ component (dependency order):

1. **utils** — copies scripts to `bin/` (no compilation)
2. **common** — `liboppcommon` (yacc/lex generated sources)
3. **nedxml** — `liboppnedxml` + executables (yacc/lex/perl generated sources)
4. **layout** — `libopplayout`
5. **eventlog** — `liboppeventlog` + `opp_eventlogtool` (perl generated sources)
6. **scave** — `liboppscave` + `opp_scavetool`
7. **sim** — `liboppsim` (msgc, conditional NETBUILDER/PARSIM)
8. **envir** — `liboppenvir` + `liboppmain` + `opp_run` (perl generated source)
9. **cmdenv** — `liboppcmdenv`
10. **qtenv** — `liboppqtenv` (moc/uic/rcc, conditional on WITH_QTENV)

### Builder function

`build_omnetpp_using_tasks(omnetpp_project, mode="release")`:
1. Get `MakefileIncConfig` from the project
2. For each component, create a `BuildOmnetppComponentTask` (a `MultipleTasks`, sequential):
   - Source generation tasks (if any)
   - `MultipleTasks` of `CppCompileTask` instances (concurrent)
   - `LinkTask` for the library
   - `CopyBinaryTask` to install to `lib/`
   - (Optional) executable link + copy tasks
3. Wrap all component tasks in a top-level `MultipleTasks` (sequential)
4. Call `.run()`

### Source file discovery

Glob `*.cc` in each component's src directory. Exclude known tool mains (`opp_nedtool.cc`, `opp_msgtool.cc`, `opp_scavetool.cc`, `opp_eventlogtool.cc`, `main.cc`). Handle subdirs (`netbuilder/`, `parsim/` for sim). Handle special C files (`sqlite3.c`, `yxml.c` compiled with CC not CXX).

### Conditional compilation

- `sim/netbuilder/*.cc` only if `WITH_NETBUILDER=yes`
- `sim/parsim/*.cc` only if `WITH_PARSIM=yes`
- qtenv skipped if `WITH_QTENV!=yes`
- Extra flags for sim if `WITH_PYTHON=yes`
- Extra flags for common if `WITH_BACKTRACE=yes`

## Step 4: Update `build.py` (simulation project builder)

Replace direct `CppCompileTask`/`LinkTask`/`MsgCompileTask` usage with the new `SimulationProjectCppCompileTask`/`SimulationProjectLinkTask`/`SimulationProjectMsgCompileTask` derived classes. Same runtime behavior, the derived `__init__` does the parameter extraction.

## Step 5: Wire into `OmnetppProject`

Add support for task-based build in `OmnetppProject.build()` (e.g. a `use_tasks=True` parameter or separate method).

## Implementation order

1. Refactor `compile.py` — generalize base classes (`BuildTask`, `CppCompileTask`, `LinkTask`, `CopyBinaryTask`, `MsgCompileTask`) to explicit parameters; add new generation task classes (`YaccTask`, `LexTask`, `PerlGenerateTask`, `MocTask`, `UicTask`, `RccTask`)
2. Create derived `SimulationProject*Task` classes in `build.py`, update `BuildSimulationProjectTask` to use them (behavior-preserving)
3. Extend `makefile_vars.py` with new variables
4. Create `build_omnetpp.py` with `OmnetppProject*Task` derived classes + component data + builder logic
5. Wire into `OmnetppProject`
6. Test
