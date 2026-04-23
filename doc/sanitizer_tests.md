# Sanitizer Tests

Sanitizer tests detect memory errors, undefined behavior, and other
bugs by running simulations with AddressSanitizer / UBSan instrumentation.
Uses the `sanitize` build mode.

## Python API

```python
run_sanitizer_tests(simulation_project=inet_project)

# Filter to a specific area with a longer time limit
run_sanitizer_tests(simulation_project=inet_project,
                    working_directory_filter="examples/ethernet",
                    cpu_time_limit="10s")
```

## Command Line

```bash
opp_run_sanitizer_tests --load "/home/user/workspace/inet/inet.opp" -p inet
```
