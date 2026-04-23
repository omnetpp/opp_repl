# GitHub Actions Integration

Dispatch CI workflows on the project's GitHub repository.  Requires a
personal access token in `~/.ssh/github_repo_token` with `repo` and
`workflow` scopes, and the `github_owner`, `github_repository`, and
`github_workflows` parameters in the project's `.opp` file.

## Python API

```python
# Dispatch a single workflow
dispatch_workflow("fingerprint-tests.yml")

# Dispatch all configured workflows
dispatch_all_workflows()

# Target a specific project and branch
dispatch_workflow("fingerprint-tests.yml",
                  simulation_project=inet_project, ref="topic/my-feature")
```
