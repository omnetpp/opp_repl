# Simulation Workflows

This document describes how a human developer and an AI assistant work with
OMNeT++/INET simulations — running them, testing them, and comparing them across
versions.

## How It Works

The human launches a Python REPL in the IDE terminal. This REPL also runs an
MCP server **in the same process**. The AI connects to this MCP server. Because
they share the same process, they share the same state: environments, simulation
results, comparison results, test results, variables — everything. When the
human creates an environment or runs a simulation, the AI can see and use the
result objects directly. When the AI runs a test, the human can inspect the
results in the REPL.

This is not file-based sharing or a separate server — the AI literally operates
on the same Python objects the human is working with.

Throughout this document, an "environment" means a specific omnetpp + inet
version combination. It can be a local checkout, a released version, or a mix:

```python
# Local working copy
env = SimulationEnvironment(
    omnetpp="/home/levy/workspace/omnetpp",
    inet="/home/levy/workspace/inet",
)

# A released version
env = SimulationEnvironment(omnetpp="6.0.3", inet="4.5.2")

# Mixed: local omnetpp, released inet
env = SimulationEnvironment(
    omnetpp="/home/levy/workspace/omnetpp",
    inet="4.5.2",
)
```

Building is automatic — the library detects stale binaries and rebuilds before
any operation. You never run old code by accident.

---

## 1. Running Simulations

### Human in the REPL

```python
env = SimulationEnvironment(omnetpp="...", inet="...")

# Run a single simulation
result = env.run(
    working_directory="examples/ethernet/arptest",
    config="ARPTest",
    sim_time_limit="10s",
)
# Simulation result: DONE in 0.42s, 1247 events

# Discover available configs
configs = env.get_configs(working_directory_filter="examples/ethernet")

# Run many simulations concurrently
results = env.run_multiple(configs, concurrent=True)

# Open in the GUI
env.run(
    working_directory="examples/ethernet/arptest",
    config="ARPTest",
    user_interface="Qtenv",
)
```

### AI via MCP

The AI performs the same operations when the user asks:

> **Human:** Run the ARPTest simulation from the ethernet examples and show
> me the results.

The AI calls `run_simulation(working_directory="examples/ethernet/arptest",
config="ARPTest", sim_time_limit="10s")` and reports the outcome.

> **Human:** Which simulation configs exist under examples/wireless?

The AI calls `list_configs(working_directory_filter="examples/wireless")` and
presents the list.

> **Human:** Run all of them.

The AI calls `run_multiple(working_directory_filter="examples/wireless",
concurrent=True)` and summarizes: *"24 simulations completed: 23 DONE, 1 ERROR
(HandoverFailing — segfault at event #891)."*

### Human + AI Together

Because the REPL and MCP server share the same process, the AI can directly
access the `result` object the human just created — no need to re-run anything:

```
Human (REPL):  result = env.run(working_directory="...", config="WirelessA")
Human (REPL):  result  # sees ERROR: segfault

Human (Chat):  "WirelessA is crashing. The result is in `result`. Can you help?"
AI:            [accesses the existing `result` object — sees the error, stdout, stderr]
AI:            [re-runs the simulation in debug mode to get a stack trace]
AI:            "The crash is a null pointer dereference in
               Ieee80211Mac::handleUpperPacket() at line 234. The packet's
               controlInfo is null because..."
```

---

## 2. Testing Simulations

### 2.1 Fingerprint Tests

Fingerprint tests verify that the simulation execution trajectory hasn't changed.

#### Human in the REPL

```python
env = SimulationEnvironment(omnetpp="...", inet="...")

# Run fingerprint tests with filtering
results = env.run_fingerprint_tests(
    working_directory_filter="examples",
    ingredients="tplx",
)
# Fingerprint test summary: 347 TOTAL, 340 PASS, 5 FAIL, 2 SKIP

# See only failures
results.print(filter="FAIL")

# Run fingerprint tests for a specific area
results = env.run_fingerprint_tests(
    working_directory_filter="examples/ospf",
)

# Update stored fingerprints after an intentional change
env.update_fingerprints(working_directory_filter="examples/ospf")
```

#### AI via MCP

> **Human:** Run fingerprint tests on the OSPF examples.

The AI calls `run_fingerprint_tests(working_directory_filter="examples/ospf",
ingredients="tplx")` and reports: *"8 tests: 6 PASS, 2 FAIL. The failures are
in OspfLinkFailure (config=LinkFailure, run=0) and OspfAreaTest
(config=AreaRouting, run=0)."*

> **Human:** Update the fingerprints for those.

The AI calls `update_fingerprints(working_directory_filter="examples/ospf")`
and confirms: *"Updated 2 fingerprints."*

#### Human + AI Together

The AI accesses the same `results` object the human just created:

```
Human (REPL):  results = env.run_fingerprint_tests()
Human (REPL):  results.print(filter="FAIL")
               # 5 failures, all in different areas

Human (Chat):  "I have fingerprint results in `results`. 5 failures — are these
               regressions from my recent changes or were they already broken?"

AI:            [inspects the `results` object directly — no need to re-run]
AI:            [creates a baseline environment and runs the same tests there]
AI:            "3 of the 5 failures are new — they pass on inet-4.5.4. The
               other 2 were already failing on the baseline. The 3 new failures
               are all in modules that include OspfRoutingTable.h, which you
               modified today."

Human (Chat):  "Update the 3 that are from my change. Leave the other 2."

AI:            [updates fingerprints for the 3 specific tests]
AI:            "Done. Updated fingerprints for OspfLinkFailure, OspfAreaTest,
               and OspfRedistribution."
```

### 2.2 Statistical Tests

Statistical tests verify that scalar simulation outputs match a stored baseline.

#### Human in the REPL

```python
results = env.run_statistical_tests(
    working_directory_filter="tests/validation",
)
# Statistical test summary: 42 TOTAL, 41 PASS, 1 FAIL

results.print(filter="FAIL")
# FAIL tests/validation/WirelessA omnetpp.ini WirelessA #0
#   module=host[0].app, name=rcvdPk:count, stored=247, current=245
```

#### AI via MCP

> **Human:** Run the validation statistical tests.

The AI runs the tests and reports: *"42 tests: 41 PASS, 1 FAIL. WirelessA
has a difference in rcvdPk:count (247 → 245) at module host[0].app."*

> **Human:** Is this difference significant?

The AI: *"The relative error is 0.8%. This is a small change in a wireless
scenario where packet loss is stochastic. Let me check if the difference is
consistent across multiple runs..."*

The AI runs the test with multiple repetitions and reports: *"Across 10
repetitions, rcvdPk:count ranges from 241 to 253 in both versions. The
difference is within normal variance — this is not a regression."*

#### Human + AI Together

```
Human (REPL):  results = env.run_statistical_tests()
Human (REPL):  # sees 3 failures

Human (Chat):  "Statistical test results are in `results`. 3 failures — which
               are real regressions vs. just noise?"

AI:            [inspects the `results` object — sees the 3 failing tests and their diffs]
AI:            [re-runs each failing test with multiple repetitions]
AI:            [compares against baseline version]
AI:            "2 of 3 are noise (values within normal stochastic variance).
               1 is a real regression: the throughput in TcpValidation dropped
               by 15%, which correlates with your change to TcpConnection.cc."
```

### 2.3 Smoke Tests

Smoke tests check that simulations don't crash.

#### Human in the REPL

```python
results = env.run_smoke_tests(cpu_time_limit="1s")
# Smoke test summary: 520 TOTAL, 518 PASS, 2 ERROR
```

#### AI via MCP

> **Human:** Run smoke tests on everything.

The AI runs them and reports: *"520 tests: 518 PASS, 2 ERROR. The errors are
in showcases/tsn/framereplication (segfault) and examples/emulation/extserver
(skipped, requires network emulation support)."*

### 2.4 Full Test Suite

#### Human in the REPL

```python
fp = env.run_fingerprint_tests()
stat = env.run_statistical_tests()
smoke = env.run_smoke_tests()
```

#### AI via MCP

> **Human:** Run the full test suite before I push.

The AI runs all three test types and produces a consolidated report:
*"Fingerprints: 347 TOTAL, 345 PASS, 2 FAIL. Statistical: 42 TOTAL, 42 PASS.
Smoke: 520 TOTAL, 520 PASS. The 2 fingerprint failures are in the OSPF module
— these are expected from your SPF change. Everything else passes."*

---

## 3. Comparing Simulations Across Versions

### 3.1 Single Simulation Comparison

Compare one simulation across two environments — any version combo vs. any other.

#### Human in the REPL

```python
env_dev = SimulationEnvironment(
    omnetpp="/home/levy/workspace/omnetpp",
    inet="/home/levy/workspace/inet",
)
env_release = SimulationEnvironment(omnetpp="6.1.0", inet="4.5.4")

result = compare(
    env_dev, env_release,
    working_directory="examples/ethernet/arptest",
    config="ARPTest",
)
# Comparison result: DIVERGENT
#   Stdout trajectory: diverges at event #312
#   Fingerprint trajectory: diverges at event #310
#   Statistical results: 2 DIFFERENT

# Inspect details
result.print_different_statistics()
# module         name         value_1    value_2    relative_error
# router.eth[0]  txPk:count   1247       1243       0.003

# Find the exact cause
result.print_divergence_cause_chain()

# Debug interactively — opens both versions in Qtenv at the divergence point
result.debug_at_fingerprint_divergence()
```

#### AI via MCP

> **Human:** Compare the ARPTest simulation between my working copy and inet
> 4.5.4.

The AI creates both environments, runs the comparison, and reports:
*"The simulations diverge at event #310. The cause is a change in the ARP
table lookup in ArpTable.cc. Statistical differences: txPk:count differs by
0.3% (1247 vs 1243). The divergence starts when host[0] sends an ARP request
that is handled differently due to your change in line 89 of ArpTable.cc."*

### 3.2 Bulk Comparison

Compare many simulations at once across two versions.

#### Human in the REPL

```python
results = compare_multiple(
    env_dev, env_release,
    working_directory_filter="examples",
)
# Comparison summary: 150 TOTAL, 142 IDENTICAL, 5 DIVERGENT, 3 DIFFERENT

results.print(filter="DIVERGENT")
results.print(filter="DIFFERENT")
```

#### AI via MCP

> **Human:** Compare all examples between my branch and the 4.5.4 release.

The AI runs the bulk comparison and summarizes: *"150 simulations compared.
142 are identical. 5 have divergent execution trajectories (all in the OSPF
module). 3 have different statistical results but identical trajectories
(normal stochastic variance in wireless scenarios)."*

### 3.3 Comparing Two Released Versions

No local checkout needed — compare any two releases directly:

#### Human in the REPL

```python
env_a = SimulationEnvironment(omnetpp="6.0.3", inet="4.5.2")
env_b = SimulationEnvironment(omnetpp="6.1.0", inet="4.5.4")

result = compare(
    env_a, env_b,
    working_directory="showcases/tsn/framereplication",
    config="FrameReplication",
)
```

#### AI via MCP

> **Human:** When did the frame replication showcase start behaving differently?
> Compare inet 4.5.2 and 4.5.4.

The AI creates both environments, runs the comparison, and reports the
divergence point and cause chain.

### 3.4 Human + AI Collaboration on Comparisons

The AI accesses the same `result` object, including its divergence details,
statistical DataFrames, and cause chain data:

```
Human (REPL):  result = compare(env_dev, env_release,
                   working_directory="examples/ospf/area",
                   config="AreaRouting")
Human (REPL):  result  # DIVERGENT at event #4521

Human (Chat):  "Comparison result is in `result`. Diverges at event #4521.
               Can you figure out what's happening?"

AI:            [inspects `result` — reads the divergence position, cause chain,
               and statistical differences directly from the object]
AI:            [reads the relevant source code in OspfRouting.cc]
AI:            "The divergence is at event #4521 where router[2] recalculates
               its routing table. In your version, the SPF algorithm picks
               a different next-hop for the 10.0.3.0/24 prefix because you
               changed the tie-breaking logic in OspfRouting.cc line 142.
               The old version used router ID as the tiebreaker; your version
               uses link cost. This changes the forwarding path for 3 routes,
               which cascades into different packet trajectories."

Human (Chat):  "That's intentional. Can you update all affected fingerprints?"

AI:            [identifies all affected tests by running comparisons]
AI:            [updates fingerprints for the affected tests]
AI:            "Updated 4 fingerprints across examples/ospf/area,
               examples/ospf/simpletest, and tests/fingerprint/ospf."
```

The human can also pick up where the AI left off:

```
Human (Chat):  "Can you also open the divergence point in Qtenv so I can
               step through it?"

AI:            "I can't open GUIs, but you can do it in the REPL:"

Human (REPL):  result.debug_at_fingerprint_divergence()
               # Opens two Qtenv instances at the divergence event
```

---

## 4. Summary: Who Does What

The REPL and MCP server run in the same Python process. Every variable,
environment, result, and comparison object is shared. There is no serialization
or file-based handoff — the AI operates on the same live Python objects.

| Action | Human (REPL) | AI (MCP) |
|---|---|---|
| Create an environment | `env = SimulationEnvironment(...)` | Same — creates it in the shared namespace |
| Run a simulation | `env.run(...)` | Same — result is accessible to both |
| List configs | `env.get_configs(...)` | Same |
| Run fingerprint tests | `env.run_fingerprint_tests(...)` | Same — human can inspect `results` afterward |
| Run statistical tests | `env.run_statistical_tests(...)` | Same |
| Run smoke tests | `env.run_smoke_tests(...)` | Same |
| Update fingerprints | `env.update_fingerprints(...)` | Same |
| Compare two versions | `compare(env_a, env_b, ...)` | Same — human can drill into `result` afterward |
| Bulk compare | `compare_multiple(env_a, env_b, ...)` | Same |
| Debug at divergence | `result.debug_at_fingerprint_divergence()` | Suggests the human run this in the REPL |
| Inspect divergence cause | `result.print_divergence_cause_chain()` | Reads the cause chain from the `result` object |
| Open GUI | `env.run(..., user_interface="Qtenv")` | Suggests the human run this in the REPL |

Because both sides operate in the same process, a build triggered by either side
is immediately visible to the other. An environment created by the human is
instantly available to the AI. A test result produced by the AI can be inspected
by the human with `results.print(filter="FAIL")`.
