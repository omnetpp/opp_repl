# Feature, Release, and All Tests

## Feature Tests

Feature tests check that simulation projects build and their simulations can be
set up correctly with different combinations of optional features enabled or disabled.

```python
run_feature_tests(simulation_project=inet_project)
```

```bash
opp_run_feature_tests --load "/home/user/workspace/inet/inet.opp" -p inet
```

## Release Tests

Release tests run a comprehensive set of checks suitable for validating a release build.

```python
run_release_tests(simulation_project=inet_project)
```

```bash
opp_run_release_tests --load "/home/user/workspace/inet/inet.opp" -p inet
```

## Running All Tests

All configured test types can be run sequentially with a single call:

```python
run_all_tests(simulation_project=inet_project)
```

```bash
opp_run_all_tests --load "/home/user/workspace/inet/inet.opp" -p inet
```
