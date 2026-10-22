# Fingerprint Tests

Fingerprint tests detect unintended behavioral changes by comparing a
hash of selected simulation state (trajectory, packet counts, etc.)
against stored baseline values.  The baseline is kept in a JSON store
file configured via the `fingerprint_store` project parameter.

## Python API

### Storing correct fingerprints

If there are no fingerprints in the store yet, they must be calculated and inserted first:

```python
update_fingerprint_test_results(simulation_project=inet_project, sim_time_limit="1s")
```

Example output:

```
[04/42] Updating fingerprint . -c PureAlohaExperiment -r 3 for 1s INSERT 856a-c13d/tplx
[11/42] Updating fingerprint . -c PureAlohaExperiment -r 10 for 1s INSERT 835c-d8e8/tplx
...
Multiple update fingerprint results: INSERT, summary: 42 INSERT (unexpected) in 0:00:01.567479
```

Updating fingerprints again when they haven't changed produces KEEP results:

```
Multiple update fingerprint results: KEEP, summary: 7 KEEP in 0:00:00.218112
```

### Running fingerprint tests

```python
r = run_fingerprint_tests(simulation_project=inet_project, sim_time_limit="1s")
```

Example output:

```
[02/42] Checking fingerprint . -c PureAlohaExperiment -r 1 for 1s PASS
...
Multiple fingerprint test results: PASS, summary: 42 PASS in 0:00:01.129969
```

PASS means the calculated fingerprint matches the stored value.

### Re-running and filtering

```python
# Re-run only the failures
r.get_fail_results().rerun()

# Filter to a specific area of the project
run_fingerprint_tests(simulation_project=inet_project,
                      working_directory_filter="examples/ethernet",
                      sim_time_limit="10s")

# Update fingerprints for a subset after intentional changes
update_fingerprint_test_results(simulation_project=inet_project,
                            working_directory_filter="examples/ethernet",
                            sim_time_limit="10s")
```

### Understanding the test result

`run_fingerprint_tests()` returns a `MultipleFingerprintTestTaskResults`
object that aggregates individual test results — one per
(config, run, ingredients) combination.  Printing it shows the overall
verdict and a summary:

```python
print(r)
# Multiple fingerprint test results: PASS, summary: 42 PASS in 0:00:01.129969
```

Each element in `r.results` is a `FingerprintTestTaskResult` with:

- **`result`** — `"PASS"`, `"FAIL"`, `"SKIP"`, `"ERROR"`, or `"CANCEL"`
- **`expected_result`** — the expected outcome stored alongside the fingerprint (usually `"PASS"`)
- **`expected`** — `True` when `result` matches `expected_result`
- **`reason`** — human-readable explanation on non-PASS outcomes (e.g. `"Fingerprint mismatch"`, `"Correct fingerprint not found"`)
- **`expected_fingerprint`** — the `Fingerprint` object loaded from the store
- **`calculated_fingerprint`** — the `Fingerprint` object computed by the simulation
- **`fingerprint_mismatch`** — `True` when the two fingerprints differ

```python
r0 = r.results[0]
print(r0.result)                   # "PASS" or "FAIL"
print(r0.expected_fingerprint)     # e.g. 856a-c13d/tplx
print(r0.calculated_fingerprint)   # e.g. 856a-c13d/tplx
print(r0.fingerprint_mismatch)     # False when they match
```

A fingerprint value like `856a-c13d/tplx` consists of the hash (`856a-c13d`)
and the ingredient letters (`tplx`).  The ingredients control which aspects of
the simulation state are hashed.  The default is `tplx` (simulation **t**ime,
module **p**ath, message c**l**ass name, and te**x**t).

### Understanding the update result

An update records all ingredients of one run at one `sim_time_limit` with
one simulation.  `update_fingerprint_test_results()` returns one
`FingerprintUpdateTaskResult` for each such simulation, with:

- **`result`** — one of:
  - `"KEEP"` — every calculated fingerprint matches the stored one; nothing changed
  - `"INSERT"` — a value is new, and no stored value changes
  - `"UPDATE"` — a stored value or its expected result changes
  - `"ERROR"` — the simulation failed or a fingerprint could not be extracted
- **`ingredient_updates`** — an `(ingredients, stored entry or None,
  calculated Fingerprint or None)` tuple for each recorded ingredient

```python
u = update_fingerprint_test_results(simulation_project=inet_project, sim_time_limit="1s")
for ur in u.results:
    print(ur.result, [str(calculated) for _, _, calculated in ur.ingredient_updates])
```

Which runs and limits an update records depends on `stored_only`:

- `stored_only=True` records only what the store holds: each stored run,
  iteration-variable run filters too, at each of its stored limits, for the
  ingredients that the store holds at that limit.  This is the normal
  update after an intentional change.
- `stored_only=False` records every ingredient for every selected run: at
  the stored limits of the run, or else at `sim_time_limit` or the limit of
  the INI file.  It inserts the values that the store does not hold yet, so
  use it with a filter to add a new config.

If all stored entries of a run and limit expect `ERROR`, an `ERROR` result
is expected.  If such a simulation now finishes, its entries get the new
value and the expected result `PASS`.

Like the test, the update applies the `fingerprint` defaults of the
project's `.opp` file.

### Fingerprint ingredients

Different ingredient strings test different aspects of the simulation:

| Ingredients | Description |
|-------------|-------------|
| `tplx`      | Default: simulation **t**ime, module **p**ath, message c**l**ass name, te**x**t |
| `~tNl`      | Network-level: uses INET's `FingerprintCalculator` |
| `~tND`      | Network-level with computed checksums/CRCs/FCS |
| `tyf`       | Includes fake-GUI events for animation reproducibility |

Each ingredient string with `~` runs with INET's `FingerprintCalculator`.
`tyf` runs with a fake GUI that calls `refreshDisplay()` with the
probability 0.001 at each opportunity, the values with which INET recorded
its `tyf` fingerprints.

You can test multiple ingredient sets at once:

```python
run_fingerprint_tests(simulation_project=inet_project,
                      ingredients_list=["tplx", "~tNl"],
                      sim_time_limit="1s")
```

When a simulation has fingerprint entries for several ingredient sets, they are
grouped by `sim_time_limit` and checked in a single simulation run for
efficiency.

### Testing against a shorter (or longer) stored baseline

The store can hold fingerprints for the same simulation at several
`sim_time_limit` values.  Pass `select_fingerprint` to pick across them
instead of matching the limit from the INI file:

```python
# Fast CI run: use whichever stored baseline has the smallest sim_time_limit.
run_fingerprint_tests(simulation_project=inet_project,
                      select_fingerprint="shortest")

# Nightly run: use the longest stored baseline.
run_fingerprint_tests(simulation_project=inet_project,
                      select_fingerprint="longest")
```

The string aliases `"shortest"` and `"longest"` resolve to
`select_fingerprint_with_smallest_sim_time_limit` and
`select_fingerprint_with_largest_sim_time_limit` respectively; pass either
the alias or the function directly, or supply your own callable that takes
a list of store entries and returns one.

When `select_fingerprint` is given, the `sim_time_limit` filter is dropped
and the selected entry's `sim_time_limit` is applied to the simulation run.
Without `select_fingerprint` the existing behavior is preserved: the
explicit `sim_time_limit` (or the one from the INI) is matched against the
store.

### The fingerprint store

Baselines are persisted in a JSON file (the path is set by the
`fingerprint_store` project parameter).  Each entry records:

- **`working_directory`**, **`ini_file`**, **`config`**, **`run_number`** — identify the simulation run
- **`sim_time_limit`** — the simulation time limit used when the fingerprint was recorded
- **`ingredients`** — the ingredient string (e.g. `"tplx"`)
- **`fingerprint`** — the hash value (e.g. `"856a-c13d"`)
- **`test_result`** — the expected test outcome (usually `"PASS"`)
- **`timestamp`** — when the value of the entry last changed

An entry without a `sim_time_limit` cannot be reproduced.  The test reports
it as an unexpected `ERROR`, and does not run it.  The CSV importer
(`opp_repl.test.fingerprint.old`) therefore takes an empty CSV limit from
the INI file.

`store.write()` sorts the entries and writes the keys of each entry in one
fixed order, so the same entries always give the same file.  A project that
keeps its store in git then sees only the changed values in a diff.

You can query or manipulate the store directly:

```python
store = get_correct_fingerprint_store(inet_project)

# Look up a specific entry
entry = store.find_entry(working_directory="examples/ethernet/lans",
                         config="General", run_number=0, ingredients="tplx")

# List all entries for a config
entries = store.filter_entries(config="General", ingredients=None,
                               sim_time_limit=None, run_number=None)

# Remove fingerprints for a subset of simulations
remove_correct_fingerprints(simulation_project=inet_project,
                            working_directory_filter="examples/ethernet")

# Remove store entries whose simulation configs no longer exist
remove_extra_correct_fingerprints(simulation_project=inet_project)
```

After any direct modifications, call `store.write()` to persist the changes.

### Printing and inspecting stored fingerprints

```python
# Print all stored correct fingerprints matching the filters
print_correct_fingerprints(simulation_project=inet_project)

# Print simulation configs that have no stored fingerprint yet
print_missing_correct_fingerprints(simulation_project=inet_project)
print_missing_correct_fingerprints(simulation_project=inet_project,
                                   ingredients="~tNl", num_runs=3)
```

## Command Line

The typical workflow when starting from scratch:

```bash
# 1. Running tests without a baseline — all tests are skipped
opp_run_fingerprint_tests --load "/home/user/workspace/omnetpp/**/*.opp" -p fifo -t 1s
# Multiple fingerprint test results: SKIP, summary: 7 SKIP (unexpected) in 0:00:00.004558

# 2. Store correct fingerprints first
opp_update_fingerprint_test_results --load "/home/user/workspace/omnetpp/**/*.opp" -p fifo -t 1s
# [2/7] Updating fingerprint . -c Fifo2 for 1s INSERT 6593-438a/tplx
# ...
# Multiple update fingerprint results: INSERT, summary: 7 INSERT (unexpected) in 0:00:00.172821

# 3. Now tests pass
opp_run_fingerprint_tests --load "/home/user/workspace/omnetpp/**/*.opp" -p fifo -t 1s
# [3/7] Checking fingerprint . -c TandemQueueExperiment for 1s PASS
# ...
# Multiple fingerprint test results: PASS, summary: 7 PASS in 0:00:00.164720

# 4. Updating again when nothing changed — values are kept
opp_update_fingerprint_test_results --load "/home/user/workspace/omnetpp/**/*.opp" -p fifo -t 1s
# [5/7] Updating fingerprint . -c TandemQueueExperiment -r 2 for 1s KEEP 4cbd-3dae/tplx
# ...
# Multiple update fingerprint results: KEEP, summary: 7 KEEP in 0:00:00.218112
```

Both commands also take these options:

- `--ingredients INGREDIENTS` — use these ingredients instead of the
  project's; give the option once for each ingredient string.
- `--stored-only` and `--no-stored-only` — use only the runs with a stored
  fingerprint, or every selected run (see the update result above).
- `--append-args ARGS...` — pass all following arguments to `opp_run`, for
  example `--append-args --fingerprint-modules='**.host[0].**'` to find the
  module where a fingerprint changes.  It must be the last option.
- `--split-count N --split-index I` — run only slice `I` of `N`, for a CI
  matrix (see [Tasks](tasks.md#running-multiple-tasks)).
