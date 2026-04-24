# SSH Cluster Execution

Distribute simulation tasks across multiple machines using Dask
(requires the `cluster` extra: `dask` and `dask.distributed`).

## Why use a cluster?

Large-scale simulation campaigns (fingerprint tests across hundreds of
configs, parameter sweeps, etc.) can take hours on a single machine.
The SSH cluster spreads tasks across every available node with automatic
load balancing — as if all machines were a single computer.

## Prerequisites

All cluster nodes must satisfy:

- **Passwordless SSH** — every node can SSH into every other node
  (including itself) without user interaction.
- **Hostname resolution** — scheduler and worker hostnames can be resolved
  on all nodes.
- **Same Python environment** — the Python version and all required
  libraries must match across nodes.
- **No firewall** — the Dask scheduler must be able to reach workers on
  their ephemeral ports.
- **Compiled binaries** — the simulation project must be built (both
  release and debug if needed) and the binaries must be available on every
  node.

## How it works

The cluster uses **Dask Distributed** (`dask.distributed.SSHCluster`)
under the hood:

1. `SSHCluster.start()` launches a Dask **scheduler** on the scheduler
   hostname and a Dask **worker** on each worker hostname via SSH.
2. A `dask.distributed.Client` connects to the scheduler and registers
   it as the default for all subsequent `dask.compute()` calls.
3. When tasks run with `scheduler="cluster"`, each `SimulationTask` is
   wrapped in `dask.delayed()` and submitted to the cluster.  Dask
   distributes tasks to workers and collects results transparently.
4. Results are returned as a normal `MultipleTaskResults`, identical to
   local execution.

A live **dashboard** is available at http://localhost:8797 while the
cluster is running, showing task progress, worker load, and memory usage.

## Setup

Create an SSH cluster by specifying the scheduler and worker hostnames:

```python
from opp_repl.common.cluster import SSHCluster

c = SSHCluster(scheduler_hostname="node1.local",
               worker_hostnames=["node1.local", "node2.local"])
c.start()
```

The scheduler node is typically also a worker (it appears in both
`scheduler_hostname` and `worker_hostnames` in the example above).

Verify the cluster is operating correctly:

```python
c.run_gethostname(12)
# 'node1, node2, node2, node1, node2, node1, ...'
```

The output should contain a permutation of all worker hostnames,
confirming that tasks are distributed across the cluster.

### Nix shell support

If the cluster nodes use Nix for environment management, pass the shell
name so that tasks execute inside the correct environment:

```python
c = SSHCluster(scheduler_hostname="node1.local",
               worker_hostnames=["node1.local", "node2.local"],
               nix_shell="omnetpp-dev")
c.start()
```

## Distributing binaries

Build the project and copy binaries to all worker nodes:

```python
p = get_simulation_project("aloha")
build_project(simulation_project=p, mode="release")
p.copy_binary_simulation_distribution_to_cluster(["node1.local", "node2.local"])
```

Binaries are incrementally copied using `rsync`, so only changed files
are transferred.  This step is required whenever the project is rebuilt.

## Running on the cluster

Use the same `run_simulations()` function with `scheduler="cluster"`:

```python
run_simulations(mode="release", config_filter="PureAlohaExperiment",
                scheduler="cluster", cluster=c)
```

You can also collect tasks and run them separately:

```python
mt = get_simulation_tasks(simulation_project=p, mode="release",
                          config_filter="PureAlohaExperiment",
                          scheduler="cluster", cluster=c)
mt.run()
```

All task types (simulations, fingerprint tests, updates, etc.) support
cluster execution — any `MultipleTasks` with `scheduler="cluster"` will
dispatch to the cluster.

## Scheduler modes

The `scheduler` parameter on `MultipleTasks` (and `run_simulations()`)
controls how concurrent tasks are dispatched:

| Value | Description |
|---|---|
| `"thread"` | Thread pool on the local machine (default) |
| `"process"` | Process pool on the local machine |
| `"cluster"` | Dask distributed across SSH nodes |

For local execution, `"thread"` is usually fastest because simulations
run as subprocesses and threads avoid the overhead of inter-process
serialization.  `"process"` is useful when tasks do significant
Python-side work.  `"cluster"` is for multi-machine execution.

## Command line

From the command line, pass `--hosts` with a comma-separated list of
hostnames.  The first hostname is used as the scheduler:

```bash
opp_run_simulations --hosts node1.local,node2.local \
    --load inet.opp -p inet --config-filter PureAloha
```

Binaries are automatically distributed to the workers before starting.
An optional `--nix-shell` flag selects the Nix environment on remote
nodes.

## Stopping the cluster

Exiting the interactive Python session automatically stops the SSH
cluster.  The Dask scheduler and workers on remote nodes are shut down
via SSH.

## Troubleshooting

Common issues:

- **"Connection refused"** — check that no firewall blocks the Dask
  scheduler port (default 8786) and the dashboard port (8797).
- **Import errors on workers** — ensure the same Python version and
  packages are installed on all nodes.
- **"Permission denied" on SSH** — verify passwordless SSH with
  `ssh node2.local hostname` from every node.
- **Stale workers** — if a previous run did not shut down cleanly, kill
  leftover `dask-worker` processes on the affected nodes.
