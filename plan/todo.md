# TODO

## Code fixes

- `SimulationProject.copy_binary_simulation_distribution_to_cluster()`
  is called from `opp_repl/main.py:86` (the `--hosts` CLI path) but is
  not defined anywhere on `SimulationProject`. The `--hosts` flow is
  currently broken — calling it raises `AttributeError`. Either
  implement the method (e.g. rsync the build artifacts to each worker
  hostname) or remove the `--hosts` CLI flow. The doc example in
  `doc/cluster.md` has been dropped pending this fix; restore once the
  method exists.

- `SimulationConfig.clean_simulation_results()`
  (`opp_repl/simulation/config.py:143-150`) currently does
  `shutil.rmtree(results/)`, deleting the whole `results/` folder.
  Cleaning the results of a single simulation should not remove the
  `results/` folder itself — only the produced result files
  (`.sca`, `.vec`, `.vci`, `.elog`, `.log`, `.rt`), matching the
  behaviour of `SimulationTask.clear_result_folder()`
  (`opp_repl/simulation/task.py:399-404`).
  Once fixed, `doc/tasks.md:207-208` (which currently describes the
  per-extension behavior) becomes accurate, and
  `doc/running_simulations.md:130` ("deletes the `results/` folder")
  needs to be updated to match the new selective behavior.
