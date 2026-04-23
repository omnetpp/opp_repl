# Coverage Reports

Coverage reports show which lines of C++ source code are exercised by
simulations.  Uses the `coverage` build mode and LLVM's coverage tools.

## Python API

```python
# Generate and open a coverage report in the browser
open_coverage_report(simulation_project=inet_project,
                     working_directory_filter="examples/ethernet",
                     sim_time_limit="10s")

# Just generate the report without opening it
generate_coverage_report(simulation_project=inet_project,
                         working_directory_filter="examples/ethernet",
                         sim_time_limit="10s")
```
