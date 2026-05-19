# Plan: make IPython the only required runtime dependency

## Goal

`pip install opp_repl` (no extras) into a fresh venv that has only `ipython`
must be enough for `import opp_repl` to succeed without errors. Every other
third-party library currently used (`pandas`, `numpy`, `matplotlib`, `scipy`,
`optimparallel`, `dask`, `distributed`, `requests`, `py4j`, `mcp`, `anyio`)
must be **optional** and gated behind an extras group.

Success is measured by the existing self test
[opp_repl/test/self/dependency.py](opp_repl/test/self/dependency.py),
which spins up a clean venv per scenario, installs `opp_repl` (with or
without an extras group), and checks that `python -c "import opp_repl"`
returns exit code 0. The `test_no_optional_modules` case is the one
currently failing today; it must pass at the end of this work.

## Current state

Established convention (already in place for `mcp`, `dask`, `requests`,
`py4j`, `scipy`, `matplotlib`):

- The module keeps its third-party imports at file top-level.
- Its parent `__init__.py` gates the `from … import *` with
  `importlib.util.find_spec("<pkg>")`.

Files that already follow this convention correctly:
[opp_repl/common/cluster.py](opp_repl/common/cluster.py),
[opp_repl/common/github.py](opp_repl/common/github.py),
[opp_repl/common/ide.py](opp_repl/common/ide.py),
[opp_repl/common/mcp.py](opp_repl/common/mcp.py),
[opp_repl/simulation/optimize.py](opp_repl/simulation/optimize.py),
[opp_repl/test/chart.py](opp_repl/test/chart.py).

Files that **violate** the rule (third-party module-level imports of
packages not guaranteed to be installed):

| File | Line | Import | Required extra group today |
| --- | --- | --- | --- |
| [opp_repl/common/util.py](opp_repl/common/util.py) | 12 | `import pandas` | none — pandas is listed as required |
| [opp_repl/simulation/task.py](opp_repl/simulation/task.py) | 23 | `import pandas as pd` | same |
| [opp_repl/test/statistical.py](opp_repl/test/statistical.py) | 13 | `import pandas` | same |

These three modules are star-imported unconditionally by their respective
`__init__.py`:
[opp_repl/common/__init__.py:12](opp_repl/common/__init__.py#L12),
[opp_repl/simulation/__init__.py:18](opp_repl/simulation/__init__.py#L18),
[opp_repl/test/__init__.py:23](opp_repl/test/__init__.py#L23). They are
core enough that gating those star-imports on pandas would knock out
unrelated functions other modules depend on, so the fix has to be
**inside** the three files, not in the `__init__.py`.

`pyproject.toml` lines 15–20 also list `pandas`, `matplotlib`, and `numpy`
as required dependencies, which contradicts the goal.

## Changes

### 1. `pyproject.toml`

Reduce the required `dependencies` list to just `ipython`. Move
`pandas` into a new extras group (call it `data`) and add it to `all`.
`matplotlib` and `numpy` are already in the `chart` group — just remove
them from the required list.

```toml
dependencies = [
    "ipython",
]

[project.optional-dependencies]
data = [
    "pandas",
]
# ...existing groups unchanged: mcp, cluster, chart, optimize, github, ide ...
all = [
    "dask",
    "distributed",
    "matplotlib",
    "mcp",
    "numpy",
    "optimparallel",
    "pandas",       # <- add
    "py4j",
    "requests",
    "scipy",
]
```

Also extend [opp_repl/test/self/dependency.py:22](opp_repl/test/self/dependency.py#L22)
to include `"data"` in `OPTIONAL_GROUPS` and add a matching
`test_optional_data` method, so the new extra is covered the same way as
the others.

### 2. `opp_repl/common/util.py`

The module-level `pandas.set_option('display.float_format', …)` call at
[opp_repl/common/util.py:22](opp_repl/common/util.py#L22) is what makes
the bare `import pandas` necessary at the top. Replace the top-level
import + call with a guarded version:

```python
try:
    import pandas
    pandas.set_option('display.float_format', lambda x: '%g' % x)
except ImportError:
    pandas = None
```

All other pandas references in this file
([opp_repl/common/util.py:486-489](opp_repl/common/util.py#L486-L489),
[opp_repl/common/util.py:647](opp_repl/common/util.py#L647),
[opp_repl/common/util.py:791,799,810,811,879](opp_repl/common/util.py#L791))
are already inside function bodies, so they'll only fail if the user
actually calls those functions without pandas — which is the desired
behavior.

### 3. `opp_repl/simulation/task.py`

The top-level `import pandas as pd` at
[opp_repl/simulation/task.py:23](opp_repl/simulation/task.py#L23) is
referenced only by three `pd.concat(...)` calls at lines 604, 616, 628
(inside `get_scalars` / `get_vectors` / `get_histograms` of
`MultipleSimulationResults`). Move the import into each of those methods
(or into one shared helper) and drop the top-level import. No
module-level state depends on pandas in this file.

### 4. `opp_repl/test/statistical.py`

Top-level `import pandas` at
[opp_repl/test/statistical.py:13](opp_repl/test/statistical.py#L13). The
only non-docstring usage is in function bodies (the references at lines
81–82 are just type names in docstrings). Move the import into the
function(s) that use it, or — given that the whole module is about
statistical comparison of pandas results — wrap the top-level import in
the same `try: … except ImportError: pandas = None` shape used for
`common/util.py`. The latter is less invasive and keeps the
helpful `NameError` → `pandas is None` symptom local.

### 5. Verify nothing else regressed

Run the self test inside the project venv:

```
python -m unittest opp_repl.test.self.dependency -v
```

All eight scenarios (no extras + each of mcp/cluster/chart/optimize/
github/ide/data + all) must pass. The currently-failing
`test_no_optional_modules` is the canonical signal.

## Out of scope

- **Splitting modules** to physically separate pandas-using code from
  pandas-free code. Not needed — try/except + lazy import is the cheaper
  fix and matches the existing pattern. Worth revisiting only if the
  pandas-dependent surface area grows.
- **Adding informative error messages** when a user calls a function
  whose backing library is missing. Today the convention is "let the
  `NameError`/`ImportError` propagate", consistent with how
  `simulation/optimize.py` and `test/chart.py` behave.
- **Removing the `data` extra from `all`.** Keep `all` exhaustive so
  `pip install opp_repl[all]` is still the one-shot "give me
  everything" install.
- **Touching IPython usage.** IPython is the one required dependency and
  is imported at top level in
  [opp_repl/common/util.py:8](opp_repl/common/util.py#L8) and
  [opp_repl/common/ide.py:1](opp_repl/common/ide.py#L1). Leave as is.

## Risk notes

- Other code that imports from `opp_repl.common.util` and expects the
  name `pandas` to be a module (rather than `None`) will break in
  pandas-less installs. A grep across the package shows no such
  cross-module `from opp_repl.common.util import pandas` — usages are
  all `opp_repl.common.util.<function>(...)` — so this is safe in
  practice, but worth re-grepping right before merge.
- `pyproject.toml` is consumed by `setuptools_scm` and packaging — be
  careful that the rewritten `dependencies` block parses (the original
  uses TOML array-of-strings; keep the same form).
