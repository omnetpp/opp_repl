# OMNeT++/INET Simulation Python Library — Plan

## 1. Problem Statement

### 1.1 The Current Pain

Working with OMNeT++/INET simulations today is a multi-step manual process that
imposes constant friction on both development and testing:

**Environment setup is fragile and manual.** Before doing anything, you must
`source setenv` in both the omnetpp and inet directories, in the right order.
Forget this (or open a new terminal) and nothing works. The environment is
invisible — you can't easily tell which omnetpp/inet combination is active,
and there's no protection against accidentally mixing versions.

**You are locked to one version at a time.** The environment variables
(`__omnetpp_root_dir`, `INET_ROOT`) point to a single omnetpp and a single inet
checkout. To test against a different version, you must close everything, switch
checkouts, re-source the environment, rebuild, and start over. Comparing behavior
across versions requires maintaining separate terminal sessions with different
environments — error-prone and tedious.

**Building is opaque and error-prone.** After editing C++ source files, you must
remember to rebuild before running simulations. If you forget, you run against
stale binaries and get misleading results. There is no automatic staleness
detection. The build process itself requires knowing which make targets to invoke,
in which directory, with which mode flags.

**Running simulations requires directory navigation.** Each simulation example
lives in its own directory with its own `omnetpp.ini`. You must `cd` there,
figure out the right executable and command-line flags, and invoke it manually.
The `bin/inet` script helps but still requires being in the right directory.

**Testing is disconnected from development.** Running fingerprint tests,
statistical tests, or smoke tests requires separate command-line tools, each with
their own argument conventions. There's no unified way to say "run all tests
related to what I just changed" or "check if my change broke anything."

**Cross-version comparison is extremely difficult.** If you want to compare
simulation behavior between your working copy and a released version, or between
two different releases, you must manually set up two separate environments, run
the same simulation in both, and compare the outputs by hand. The existing
comparison infrastructure (`inet.simulation.compare`) only works within a single
environment.

**AI cannot participate.** There is no machine-accessible interface. An AI
assistant in Windsurf can read and edit source code, but it cannot run simulations,
check for regressions, or investigate test failures without asking the user to
manually execute commands and paste output back.

### 1.2 The Goal

A standalone Python library that eliminates all of the above friction:

- **Any version, any time** — work with any combination of omnetpp + inet
  versions simultaneously, specified by path or version number
- **Zero setup** — no sourcing setenv, no directory navigation, no environment
  variable juggling
- **Transparent builds** — compilation happens automatically when needed, never
  run stale binaries
- **Cross-version comparison** — compare any version combination against any
  other version combination with a single function call
- **Unified testing** — fingerprint, statistical, and smoke tests through the
  same interface
- **Human + AI** — both the developer (via a Python REPL in Windsurf) and the AI
  assistant (via an MCP server) can drive simulations using the same capabilities

---

## 2. What You Can Do With It

This section describes capabilities from the user's and the AI's perspective,
independent of how the implementation works.

### 2.1 Specify Any Version Combination

Point to any omnetpp + inet combination. Local checkouts, opp_env-managed
installs, or version numbers — all work interchangeably:

```python
# Your current working copy
env = SimulationEnvironment(
    omnetpp="/home/levy/workspace/omnetpp",
    inet="/home/levy/workspace/inet",
)

# A specific released version (resolved via opp_env)
env_old = SimulationEnvironment(omnetpp="6.0.3", inet="4.5.2")

# Mix: your omnetpp with a released inet
env_mix = SimulationEnvironment(
    omnetpp="/home/levy/workspace/omnetpp",
    inet="4.5.2",
)
```

You never source setenv, never set environment variables, never cd anywhere.
The environment object handles everything internally.

### 2.2 Run Simulations

Run any simulation from anywhere, without being in its directory:

```python
result = env.run(
    working_directory="examples/ethernet/arptest",
    config="ARPTest",
    sim_time_limit="10s",
)
# result: DONE in 0.42s, 1247 events

# If the binary is stale, it rebuilds automatically — you never run old code.
```

Discover available configs with filtering:

```python
configs = env.get_configs(working_directory_filter="examples/ethernet")
# [SimulationConfig(ARPTest), SimulationConfig(ARPTest2), SimulationConfig(LargeNet), ...]
```

Run many simulations concurrently:

```python
results = env.run_multiple(configs, concurrent=True)
```

Open a simulation in the GUI debugger:

```python
env.run(
    working_directory="examples/ethernet/arptest",
    config="ARPTest",
    user_interface="Qtenv",
)
```

### 2.3 Run Tests

**Fingerprint tests** — check whether simulations produce the same execution
trajectory as before:

```python
results = env.run_fingerprint_tests(
    working_directory_filter="examples",
    ingredients="tplx",
)
# Fingerprint test summary: 347 TOTAL, 340 PASS, 5 FAIL, 2 SKIP

results.print(filter="FAIL")

# Update stored fingerprints after an intentional change:
env.update_fingerprints(working_directory_filter="examples")
```

**Statistical tests** — verify that scalar outputs match a stored baseline:

```python
results = env.run_statistical_tests(
    working_directory_filter="tests/validation",
)
# Statistical test summary: 42 TOTAL, 41 PASS, 1 FAIL
# FAIL: WirelessA — module=host[0].app, name=rcvdPk:count, stored=247, current=245
```

**Smoke tests** — quick check that simulations don't crash:

```python
results = env.run_smoke_tests(cpu_time_limit="1s")
# Smoke test summary: 520 TOTAL, 520 PASS
```

### 2.4 Compare Any Version Against Any Other Version

This is the most powerful capability. Compare simulation behavior across two
completely different omnetpp/inet version combinations:

```python
env_a = SimulationEnvironment(
    omnetpp="/home/levy/workspace/omnetpp",
    inet="/home/levy/workspace/inet",
)
env_b = SimulationEnvironment(omnetpp="6.0.3", inet="4.5.2")

result = compare(
    env_a, env_b,
    working_directory="examples/ethernet/arptest",
    config="ARPTest",
)
```

The comparison reports three levels of detail:

- **Stdout trajectory** — did the log output diverge? At which event?
- **Fingerprint trajectory** — did the execution trajectory diverge?
  At which event? What was the cause chain?
- **Statistical results** — which scalars changed? By how much?

```python
result.is_identical                    # False
result.stdout_divergence               # diverges at event #4521
result.fingerprint_divergence          # diverges at event #4519
result.statistical_differences         # DataFrame: 3 scalars differ
result.print_different_statistics()    # module=router.ospf, name=spfRuns, ...
```

Drill into divergences:

```python
# Launch both versions in Qtenv, paused at the divergence point:
result.debug_at_fingerprint_divergence()

# Print the cause chain leading to the divergence:
result.print_divergence_cause_chain()
```

Compare entire test suites across versions:

```python
results = compare_multiple(
    env_a, env_b,
    working_directory_filter="examples",
)
# Comparison summary: 150 TOTAL, 142 IDENTICAL, 5 DIVERGENT, 3 DIFFERENT
```

### 2.5 Typical Use Cases

#### "Did my change break anything?"

You just modified `OspfRouting.cc`. Before committing:

```python
env = SimulationEnvironment(omnetpp="...", inet="...")
results = env.run_fingerprint_tests(working_directory_filter="examples/ospf")
results = env.run_fingerprint_tests(working_directory_filter="tests/fingerprint")
```

Or ask the AI: *"Run all fingerprint tests related to OSPF and tell me if
anything changed."*

#### "How does my working copy compare to the last release?"

```python
env_dev = SimulationEnvironment(omnetpp="/home/levy/workspace/omnetpp", inet="/home/levy/workspace/inet")
env_release = SimulationEnvironment(omnetpp="6.1.0", inet="4.5.4")

results = compare_multiple(env_dev, env_release, working_directory_filter="examples")
results.print(filter="DIVERGENT")
```

#### "Compare two released versions to find when a behavior changed"

```python
env_a = SimulationEnvironment(omnetpp="6.0.3", inet="4.5.2")
env_b = SimulationEnvironment(omnetpp="6.1.0", inet="4.5.4")

result = compare(env_a, env_b,
    working_directory="showcases/tsn/framereplication",
    config="FrameReplication",
)
result.print_divergence_cause_chain()
```

#### "Investigate a regression"

The AI is asked: *"The ARPTest fingerprint is failing on my branch. Can you
figure out why?"*

The AI:
1. Runs the fingerprint test to confirm the failure and get the calculated hash
2. Runs the same test against the baseline release to see if it passes there
3. Runs a cross-version comparison to find the exact event where behavior diverges
4. Reads the source code around that event to identify the likely cause
5. Reports back: *"The divergence starts at event #4521, which is an ARP reply
   in the EthernetMac module. Your change to MacRelayUnitBase.cc on line 47
   altered the forwarding decision..."*

#### "Run the full test suite before a release"

```python
env = SimulationEnvironment(omnetpp="6.1.0", inet="/home/levy/workspace/inet")
fp_results = env.run_fingerprint_tests()
stat_results = env.run_statistical_tests()
smoke_results = env.run_smoke_tests()
```

Or ask the AI: *"Run the full test suite (fingerprints, statistical, smoke) and
give me a summary."*

#### "Open a specific simulation in the GUI for debugging"

```python
env = SimulationEnvironment(omnetpp="...", inet="...")
env.run(
    working_directory="examples/wireless/handover",
    config="Handover",
    user_interface="Qtenv",
    mode="debug",
)
```

---

## 3. Windsurf Integration: Human + AI in the Same Process

### 3.1 Unified REPL + MCP Server

The human launches a Python REPL in the Windsurf terminal. This REPL also runs
an MCP server **in the same process**. The AI (Cascade) connects to this MCP
server. Because they share the same process, they share the same Python objects:
environments, simulation results, comparison results, test results — everything.

```
┌─────────────────────────────────────────────┐
│ Single Python Process                       │
│                                             │
│  ┌──────────────┐     ┌──────────────────┐  │
│  │ IPython REPL │     │ MCP Server       │  │
│  │ (human types │     │ (AI calls tools) │  │
│  │  here)       │     │                  │  │
│  └──────┬───────┘     └────────┬─────────┘  │
│         │    shared namespace  │            │
│         ▼                      ▼            │
│  ┌──────────────────────────────────────┐   │
│  │ env, result, results, env_old, ...   │   │
│  │ (same Python objects)                │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

This is not file-based sharing — the AI literally operates on the same live
Python objects the human is working with. When the human creates `env` in the
REPL, the AI can call methods on that same `env`. When the AI stores a result
in `fp_results`, the human can type `fp_results.print(filter="FAIL")`.

```
$ oppsim repl
MCP server started on stdio (AI can connect)

>>> env = SimulationEnvironment(omnetpp="/home/levy/workspace/omnetpp", inet="/home/levy/workspace/inet")
>>> result = env.run(working_directory="examples/ethernet/arptest", config="ARPTest")
Simulation result: DONE in 0.42s, 1247 events
```

At this point the human asks the AI in chat: *"The result is in `result`, can
you check what the throughput was?"* — and the AI can read `result` directly.

### 3.2 Collaborative Workflows

| The human... | Then the AI can... |
|---|---|
| Creates `env` in the REPL | Use the same `env` object via MCP |
| Runs a simulation → `result` | Inspect `result` (stdout, stats, fingerprint) |
| Runs fingerprint tests → `results` | Filter and analyze `results`, compare against baseline |
| Runs a comparison → `cmp` | Read `cmp.divergence_cause_chain`, `cmp.statistical_differences` |
| Asks "did I break anything?" | Run targeted tests using the existing `env` |
| Asks "why did this fingerprint change?" | Inspect the result, compare against baseline, trace cause chain |
| Says "update the fingerprints" | Call `env.update_fingerprints(...)` on the shared `env` |
| Says "open this in Qtenv" | Suggests the REPL command (AI can't open GUIs) |
| Edits C++ source code | Run tests on the same `env` (auto-rebuilds) |

The reverse also works — the AI creates objects that the human can use:

| The AI... | Then the human can... |
|---|---|
| Creates `env_baseline` for comparison | Use it in the REPL: `compare(env, env_baseline, ...)` |
| Runs tests → stores in `test_results` | `test_results.print()`, `test_results.print(filter="FAIL")` |
| Runs comparison → stores in `cmp` | `cmp.debug_at_fingerprint_divergence()` to open Qtenv |

---

## 4. Relationship to Existing Components

### 4.1 Relationship to the INET Python Library (`inet/python/inet/`)

The existing INET Python library already has all the core simulation logic:
config parsing, task execution, fingerprint/statistical/smoke tests, comparison,
and build management. However, it is tightly coupled to a single inet checkout
via environment variables set by `source setenv`.

**The new library is a thin orchestration layer on top of the existing one.**
It does NOT reimplement config parsing, test logic, or comparison algorithms.
Instead, each `SimulationEnvironment` delegates to the existing `inet` Python
package from its own inet checkout:

```
oppsim (new)                          inet/python/inet/ (existing, per checkout)
┌─────────────────────────┐           ┌──────────────────────────┐
│ SimulationEnvironment   │──uses────>│ SimulationProject        │
│  - version resolution   │           │ SimulationConfig         │
│  - env var construction │           │ SimulationTask           │
│  - build orchestration  │           │ fingerprint/stat tests   │
│  - cross-version compare│           │ comparison logic         │
│  - MCP server           │           │ build system             │
│  - REPL                 │           └──────────────────────────┘
└─────────────────────────┘           (one copy per inet checkout)
```

When you call `env.run_fingerprint_tests(...)`, the new library:
1. Ensures the environment is built
2. Sets up the correct env vars (INET_ROOT, __omnetpp_root_dir, PYTHONPATH)
3. Delegates to the existing `inet.test.fingerprint.run_fingerprint_tests()` —
   either by importing it with the right sys.path, or by spawning a subprocess
   with the correct PYTHONPATH

For cross-version comparison, each side runs in its own environment (each using
its own copy of the `inet` library), and results are compared at the `oppsim`
level.

This means:
- No duplication of config parsing, test logic, or comparison logic
- The existing inet library continues to evolve independently
- Each inet version uses its own matching Python library (version-specific
  quirks are handled naturally)
- The new library only adds what's missing: multi-version orchestration, MCP,
  REPL integration

### 4.2 Relationship to opp_env

`opp_env` is a workspace/package manager. It downloads, patches, and builds
specific versions of omnetpp/inet (using Nix for reproducibility). The new
library uses opp_env as a **backend for version resolution**:

```
oppsim (new)          opp_env                    omnetpp/inet installs
┌───────────┐         ┌──────────────┐           ┌─────────────────┐
│ "give me  │──asks──>│ workspace    │──manages──>│ omnetpp-6.1.0/  │
│  inet     │         │ management   │           │ inet-4.5.4/     │
│  4.5.4"   │         │ download     │           │ omnetpp-6.0.3/  │
│           │<─paths──│ build        │           │ inet-4.5.2/     │
└───────────┘         │ nix shell    │           └─────────────────┘
                      └──────────────┘
```

- When you pass an **explicit path**, opp_env is not involved at all
- When you pass a **version string** like `"4.5.4"`, the new library finds it
  in an opp_env workspace, or asks opp_env to install it
- The new library never reimplements opp_env's downloading, patching, or Nix
  shell management

### 4.3 Summary

| Component | Role | Changed? |
|---|---|---|
| `inet/python/inet/` | Simulation engine — runs sims, tests, comparisons (one copy per inet checkout) | No |
| `opp_env` | Package manager — downloads, patches, builds specific versions | No |
| `oppsim` (new) | Orchestration — multi-version management, delegates to inet library per-environment, MCP server, REPL | New |

---

## 5. Architecture

### 5.1 SimulationEnvironment

The central abstraction. Encapsulates an (omnetpp, inet) pair and provides all
operations. Internally it:
- Resolves paths (from explicit paths, opp_env workspace, or version strings)
- Constructs environment variables programmatically (no setenv sourcing)
- Tracks build staleness and triggers rebuilds when needed
- Delegates simulation/test operations to the existing inet Python library

### 5.2 Build Management

Before any operation, the library checks if binaries are up-to-date:
- For explicit-path environments: compare source timestamps against `out/` artifacts
- For opp_env environments: use opp_env's build commands

Build state is cached by `(omnetpp_git_hash, inet_git_hash, mode)` so you never
run stale code and never rebuild unnecessarily.

### 5.3 Unified REPL + MCP Server

A single Python process runs both the IPython REPL (for the human) and the MCP
server (for the AI). They share the same Python namespace, so the human and AI
operate on the same live objects — environments, results, comparisons. The MCP
server runs on a background thread within the REPL process and communicates via
stdio with Windsurf/Cascade.

---

## 6. Package Structure

```
oppsim/                          # working name
├── pyproject.toml
├── README.md
├── src/
│   └── oppsim/
│       ├── __init__.py          # public API, convenience imports
│       ├── environment.py       # SimulationEnvironment
│       ├── version.py           # Version resolution (paths, opp_env)
│       ├── build.py             # Build management and caching
│       ├── config.py            # SimulationConfig (INI parsing delegation)
│       ├── task.py              # SimulationTask, SimulationResult
│       ├── compare.py           # Cross-version comparison
│       ├── repl.py              # Interactive REPL entry point
│       ├── test/
│       │   ├── __init__.py
│       │   ├── fingerprint.py   # Fingerprint test delegation
│       │   ├── statistical.py   # Statistical test delegation
│       │   └── smoke.py         # Smoke test delegation
│       ├── mcp/
│       │   ├── __init__.py
│       │   └── server.py        # MCP server for Windsurf/AI
│       └── util.py              # Shared utilities
└── tests/
    └── ...
```

## 7. Dependencies

- `mcp` — MCP Python SDK for the server
- `ipython` — interactive REPL
- `pandas` — statistical result comparison
- `rich` — colored terminal output, progress bars

No dependency on `dask`, `distributed`, or `py4j` (those are inet-specific).

## 8. Implementation Phases

### Phase 1: Core (SimulationEnvironment + explicit paths)
- SimulationEnvironment with explicit omnetpp/inet paths
- Programmatic env var construction (no setenv sourcing)
- Transparent build (staleness detection + auto-rebuild)
- Run single simulations via subprocess
- Basic SimulationResult with stdout/stderr/exit code

### Phase 2: Config Discovery + Multiple Runs
- Config discovery by delegating to the inet Python library
- Filtering by working directory, config name, etc.
- Concurrent execution of multiple simulations
- SimulationResult with scalar/vector file reading

### Phase 3: Testing
- Fingerprint tests (delegating to inet's fingerprint infrastructure)
- Statistical tests (delegating to inet's statistical infrastructure)
- Smoke tests
- Test result reporting and filtering

### Phase 4: Cross-Version Comparison
- compare() and compare_multiple() functions
- Stdout trajectory comparison
- Fingerprint trajectory comparison
- Statistical result comparison (DataFrame-based)
- Divergence position reporting and debugging support

### Phase 5: opp_env Integration
- Version resolution via opp_env workspaces
- Automatic download/build via opp_env for missing versions
- Nix environment handling for opp_env-managed installs

### Phase 6: Windsurf Integration
- Unified REPL + MCP server in the same Python process
- MCP server on background thread, sharing the REPL's namespace
- MCP tools that operate on the same live objects as the REPL
- Windsurf MCP configuration

### Phase 7: Polish
- Build cache persistence
- Progress reporting (rich progress bars)
- Error messages and diagnostics
- Documentation and examples
