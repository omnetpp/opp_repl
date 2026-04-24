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

`update_fingerprint_test_results()` returns a
`MultipleFingerprintUpdateTaskResults` object.  Each element is a
`FingerprintUpdateTaskResult` with:

- **`result`** — one of:
  - `"KEEP"` — the calculated fingerprint matches the stored one; nothing changed
  - `"INSERT"` — no previous entry existed; a new baseline was stored
  - `"UPDATE"` — the stored value was replaced with a new one
  - `"ERROR"` — the simulation failed or no fingerprint could be extracted
- **`calculated_fingerprint`** — the newly computed `Fingerprint`

```python
u = update_fingerprint_test_results(simulation_project=inet_project, sim_time_limit="1s")
for ur in u.fingerprint_update_results:
    print(ur.result, ur.calculated_fingerprint)
```

### Fingerprint ingredients

Different ingredient strings test different aspects of the simulation:

| Ingredients | Description |
|-------------|-------------|
| `tplx`      | Default: simulation **t**ime, module **p**ath, message c**l**ass name, te**x**t |
| `~tNl`      | Network-level: uses INET's `FingerprintCalculator` |
| `~tND`      | Network-level with computed checksums/CRCs/FCS |
| `tyf`       | Includes fake-GUI events for animation reproducibility |

You can test multiple ingredient sets at once:

```python
run_fingerprint_tests(simulation_project=inet_project,
                      ingredients_list=["tplx", "~tNl"],
                      sim_time_limit="1s")
```

When a simulation has fingerprint entries for several ingredient sets, they are
grouped by `sim_time_limit` and checked in a single simulation run for
efficiency.

### The fingerprint store

Baselines are persisted in a JSON file (the path is set by the
`fingerprint_store` project parameter).  Each entry records:

- **`working_directory`**, **`ini_file`**, **`config`**, **`run_number`** — identify the simulation run
- **`sim_time_limit`** — the simulation time limit used when the fingerprint was recorded
- **`ingredients`** — the ingredient string (e.g. `"tplx"`)
- **`fingerprint`** — the hash value (e.g. `"856a-c13d"`)
- **`test_result`** — the expected test outcome (usually `"PASS"`)
- **`timestamp`** — when the entry was last written

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
