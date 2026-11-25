#!/usr/bin/env python3
# Phase 0 measurements of the test-selection plan for the runs of commands.json:
# - a plain run with its own LLVM_PROFILE_FILE (<out>/<i>/prof/%p.profraw)
# - the size of the .profraw files, the time of "llvm-profdata merge -sparse", of "show
#   --all-functions" on the sparse .profdata and of "show --all-functions" on the raw file
# - the number of functions in the binaries and the functions that ran (entry count > 0)
# - the same run under strace -f -e trace=%file and under the LD_PRELOAD trace
# Output: <out>/<i>/... and <out>/results.json
import json, os, re, resource, subprocess, sys, time

here = os.path.dirname(os.path.abspath(__file__))
out = os.path.abspath(sys.argv[1])
commands = json.load(open(os.path.join(here, "commands.json")))
only = [int(x) for x in sys.argv[2:]] or range(len(commands))

def run(c, profile, prefix=(), extra_env={}):
    env = dict(os.environ, **c["env"], **extra_env)
    env["LLVM_PROFILE_FILE"] = profile
    r0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.time()
    p = subprocess.run([*prefix, *c["args"]], cwd=c["cwd"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    wall = time.time() - start
    r1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    return dict(exit=p.returncode, wall=round(wall, 3), user=round(r1.ru_utime - r0.ru_utime, 3), sys=round(r1.ru_stime - r0.ru_stime, 3),
                verified="Fingerprint successfully verified" in p.stdout, tail=p.stdout[-300:] if p.returncode else "")

def timed(args):
    start = time.time()
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    if p.returncode:
        raise RuntimeError(f"{args[:3]} failed: {p.stderr[-500:]}")
    return time.time() - start, p.stdout

def functions_that_ran(show_output):
    # "show --all-functions" prints "  <name>:" then "    Function count: N"
    names, name = [], None
    for line in show_output.splitlines():
        if line.startswith("  ") and not line.startswith("   ") and line.endswith(":"):
            name = line[2:-1]
        elif name and line.startswith("    Function count: "):
            if int(line.split(":")[1]) > 0:
                names.append(name)
            name = None
    return names

def total_functions(show_output):
    m = re.search(r"Total functions: (\d+)", show_output)
    return int(m.group(1)) if m else None

results = json.load(open(os.path.join(out, "results.json"))) if os.path.exists(os.path.join(out, "results.json")) else {}
for i in only:
    c = commands[i]
    d = os.path.join(out, str(i))
    subprocess.run(["rm", "-rf", d])
    os.makedirs(d)
    r = dict(name=c["name"])
    # plain run, interleaved with the two traced runs, so that a change of the machine load has an effect on all three
    r["plain"] = run(c, os.path.join(d, "prof", "%p.profraw"))
    r["strace"] = run(c, os.path.join(d, "prof-strace", "%p.profraw"), prefix=["strace", "-f", "-qq", "-e", "trace=%file", "-o", os.path.join(d, "strace.txt")])
    r["preload"] = run(c, os.path.join(d, "prof-preload", "%p.profraw"), extra_env={"LD_PRELOAD": os.path.join(here, "libfiletrace.so"), "FILE_TRACE": os.path.join(d, "preload")})
    r["plain2"] = run(c, os.path.join(d, "prof-plain2", "%p.profraw"))
    raws = [os.path.join(d, "prof", f) for f in sorted(os.listdir(os.path.join(d, "prof")))]
    r["profraw_files"] = len(raws)
    r["profraw_bytes"] = sum(os.path.getsize(f) for f in raws)
    profdata = os.path.join(d, "run.profdata")
    r["merge_sparse_s"], _ = timed(["llvm-profdata", "merge", "-sparse", "-o", profdata, *raws])
    r["profdata_bytes"] = os.path.getsize(profdata)
    r["show_sparse_s"], show = timed(["llvm-profdata", "show", "--all-functions", profdata])
    ran = functions_that_ran(show)
    r["functions_in_sparse"] = total_functions(show)
    r["functions_ran"] = len(ran)
    with open(os.path.join(d, "functions.txt"), "w") as f:
        f.write("\n".join(sorted(ran)) + "\n")
    r["show_raw_s"], show_raw = timed(["llvm-profdata", "show", "--all-functions", *raws[:1]])
    r["functions_total"] = total_functions(show_raw)
    r["functions_ran_raw"] = len(functions_that_ran(show_raw))
    for k in ("merge_sparse_s", "show_sparse_s", "show_raw_s"):
        r[k] = round(r[k], 3)
    # remove the raw profiles of the traced runs; keep the plain one for the export check
    for sub in ("prof-strace", "prof-preload", "prof-plain2"):
        subprocess.run(["rm", "-rf", os.path.join(d, sub)])
    results[str(i)] = r
    print(i, r["name"][:60], r["plain"]["wall"], r["plain2"]["wall"], r["strace"]["wall"], r["preload"]["wall"], r["functions_ran"], flush=True)
    json.dump(results, open(os.path.join(out, "results.json"), "w"), indent=1)
