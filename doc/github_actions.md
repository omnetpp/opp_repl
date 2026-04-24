# GitHub Actions Integration

Trigger CI workflows on the project's GitHub repository directly from
the Python REPL or the command line, without navigating to the GitHub web
UI.

## How it works

`dispatch_workflow()` sends a
[workflow dispatch event](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#workflow_dispatch)
to the GitHub REST API.  The target repository and workflow file are
determined from the simulation project's configuration.  GitHub then
runs the workflow on its hosted runners (or self-hosted runners if
configured).

This is useful for:

- **Triggering CI after local changes** — push a branch and immediately
  kick off fingerprint tests, speed tests, or other workflows.
- **Running on a specific branch** — the `ref` parameter selects which
  branch, tag, or commit the workflow runs against.
- **Batch dispatch** — `dispatch_all_workflows()` fires all configured
  workflows in one call.

## Project configuration

Three parameters in the `.opp` file (or `SimulationProject` constructor)
identify the GitHub repository and its workflows:

```python
SimulationProject(
    name="inet",
    ...
    github_owner="inet-framework",
    github_repository="inet",
    github_workflows=["fingerprint-tests.yml", "statistical-tests.yml"],
)
```

| Parameter | Description |
|---|---|
| `github_owner` | GitHub user or organization (e.g. `"inet-framework"`) |
| `github_repository` | Repository name (e.g. `"inet"`) |
| `github_workflows` | List of workflow file names under `.github/workflows/` |

All three must be set for workflow dispatch to work.

## Authentication

A **personal access token** (classic) with `repo` and `workflow` scopes
must be stored in `~/.ssh/github_repo_token` (plain text, one line).

```bash
# Create the token at https://github.com/settings/tokens
echo "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" > ~/.ssh/github_repo_token
chmod 600 ~/.ssh/github_repo_token
```

The token is read at dispatch time and passed in the `Authorization`
header.  It is never logged or stored elsewhere.

## Python API

### Dispatch a single workflow

```python
dispatch_workflow("fingerprint-tests.yml")
```

Uses the default simulation project.  The workflow runs on the `master`
branch by default.

### Target a specific project and branch

```python
dispatch_workflow("fingerprint-tests.yml",
                  simulation_project=inet_project,
                  ref="topic/my-feature")
```

The `ref` parameter accepts branch names, tag names, or commit SHAs.

### Dispatch all configured workflows

```python
dispatch_all_workflows()
dispatch_all_workflows(simulation_project=inet_project, ref="v4.6.0")
```

Iterates over the `github_workflows` list and dispatches each one.

## Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `workflow_name` | `str` | — | Workflow file name (e.g. `"fingerprint-tests.yml"`) |
| `simulation_project` | `SimulationProject` | default project | Source of `github_owner` / `github_repository` |
| `ref` | `str` | `"master"` | Git ref to run the workflow against |

## Error handling

- If `github_owner` or `github_repository` is not configured, a
  `ValueError` is raised.
- If `github_workflows` is empty or `None`, `dispatch_all_workflows()`
  raises a `ValueError`.
- If the GitHub API returns a non-204 status (e.g. 404 for a missing
  workflow, 401 for a bad token), an exception is raised with the HTTP
  status and response body.

## Typical workflow

```python
# 1. Push your changes
#    (done outside Python, e.g. git push origin topic/my-feature)

# 2. Trigger CI from the REPL
dispatch_all_workflows(ref="topic/my-feature")

# 3. Monitor results on GitHub
#    https://github.com/inet-framework/inet/actions
```
