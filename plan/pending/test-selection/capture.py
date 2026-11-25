#!/usr/bin/env python3
# Records the exact command line, working directory and environment of fingerprint test runs in
# coverage mode, without a run. Argument: a JSON list of test names. For a name whose test skips
# (no stored fingerprint), it takes the first other test of the same folder that runs.
# Output: commands.json
import builtins, json, os, subprocess, sys
from opp_repl import *

load_opp_file(os.path.join(os.environ["INET_ROOT"], "inet.opp"))
project = determine_default_simulation_project(name="inet")
names = json.load(open(sys.argv[1]))
captured = None

class Recorder:
    def run(self, simulation_task, args):
        global captured
        config = simulation_task.simulation_config
        p = config.simulation_project
        env = p.get_env(mode=simulation_task.mode)
        captured = dict(args=args, cwd=p.get_full_path(config.working_directory),
                        env={k: v for k, v in env.items() if os.environ.get(k) != v})
        return subprocess.CompletedProcess(args, 1, "", "")

from opp_repl.simulation.project import apply_project_test_defaults
tasks = get_fingerprint_test_tasks(**apply_project_test_defaults("fingerprint", dict(simulation_project=project, mode="coverage", build=False)))
all_tasks = [g.tasks[0] for g in tasks.tasks]
devnull = open(os.devnull, "w")
result = []
for name in names:
    folder = name.split()[0]
    candidates = [t for t in all_tasks if t.simulation_task.get_parameters_string() == name] + \
                 [t for t in all_tasks if t.simulation_task.get_parameters_string().split()[0] == folder]
    for t in candidates:
        captured = None
        t.run(simulation_runner_class=Recorder, build=False, output_stream=devnull)
        if captured:
            n = t.simulation_task.get_parameters_string()
            result.append(dict(name=n, **captured))
            print("OK" if n == name else "REPLACED", n)
            break
    else:
        print("NONE", name)
json.dump(result, open("commands.json", "w"), indent=1)
print(len(result), "commands")
