# SSH Cluster Execution

Distribute simulation tasks across multiple machines using Dask
(requires the `cluster` extra).

## Setup

Create an SSH cluster by specifying the scheduler and worker hostnames:

```python
from opp_repl.common.cluster import SSHCluster

c = SSHCluster(scheduler_hostname="node1.local",
               worker_hostnames=["node1.local", "node2.local"])
c.start()
```

After starting, a live dashboard is available at http://localhost:8797.

Verify the cluster is operating correctly:

```python
c.run_gethostname(12)
# 'node1, node2, node2, node1, node2, node1, ...'
```

## Distributing binaries

Build the project and copy binaries to all worker nodes:

```python
p = get_simulation_project("aloha")
build_project(simulation_project=p, mode="release")
p.copy_binary_simulation_distribution_to_cluster(["node1.local", "node2.local"])
```

Binaries are incrementally copied using `rsync`.

## Running on the cluster

Use the same `run_simulations()` function with additional parameters:

```python
run_simulations(mode="release", filter="PureAlohaExperiment",
                scheduler="cluster", cluster=c)
```

You can also collect tasks and run them separately:

```python
mt = get_simulation_tasks(simulation_project=p, mode="release",
                          filter="PureAlohaExperiment",
                          scheduler="cluster", cluster=c)
mt.run()
```

Exiting the interactive Python session automatically stops the SSH cluster.
