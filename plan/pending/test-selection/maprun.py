#!/usr/bin/env python3
# The map run of the test-selection plan (phase 0 prototype) for the runs of a commands.json:
# each run gets its own LLVM_PROFILE_FILE, the LD_PRELOAD file trace and
# --print-instantiated-ned-types=true. After the run, the profile becomes a sparse .profdata and
# the list of functions that ran, and "-q sectioninheritance" gives the ini section chain.
# Usage: maprun.py COMMANDS_JSON OUT_DIR
# Output: OUT_DIR/<run id>/{run.json, functions.txt, ned.txt, sections.txt, trace.*, run.profdata}
import hashlib, json, os, shutil, subprocess, sys, time

here = os.path.dirname(os.path.abspath(__file__))
commands = json.load(open(sys.argv[1]))
out = os.path.abspath(sys.argv[2])
os.makedirs(out, exist_ok=True)

def run_id(name):
    return hashlib.sha1(("fingerprint " + name).encode()).hexdigest()[:8]

def functions_that_ran(show_output):
    names, name = [], None
    for line in show_output.splitlines():
        if line.startswith("  ") and not line.startswith("   ") and line.endswith(":"):
            name = line[2:-1]
        elif name and line.startswith("    Function count: "):
            if int(line.split(":")[1]) > 0:
                names.append(name)
            name = None
    return names

for c in commands:
    rid = run_id(c["name"])
    d = os.path.join(out, rid)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    env = dict(os.environ, **c["env"])
    env["LLVM_PROFILE_FILE"] = os.path.join(d, "prof", "%p.profraw")
    env["LD_PRELOAD"] = os.path.join(here, "libfiletrace.so")
    env["FILE_TRACE"] = os.path.join(d, "trace")
    start = time.time()
    p = subprocess.run([*c["args"], "--print-instantiated-ned-types=true"], cwd=c["cwd"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    wall = time.time() - start
    ned = sorted(l.split(": ", 1)[1] for l in p.stdout.splitlines() if l.startswith("instantiated NED type: "))
    open(os.path.join(d, "ned.txt"), "w").write("\n".join(ned) + "\n")
    raws = [os.path.join(d, "prof", f) for f in sorted(os.listdir(os.path.join(d, "prof")))]
    profdata = os.path.join(d, "run.profdata")
    subprocess.run(["llvm-profdata", "merge", "-sparse", "-o", profdata, *raws], check=True)
    shutil.rmtree(os.path.join(d, "prof"))
    show = subprocess.run(["llvm-profdata", "show", "--all-functions", profdata], stdout=subprocess.PIPE, text=True, check=True).stdout
    open(os.path.join(d, "functions.txt"), "w").write("\n".join(sorted(functions_that_ran(show))) + "\n")
    args = c["args"]
    query = args[:args.index("-r") + 2] + ["-q", "sectioninheritance"]
    q = subprocess.run(query, cwd=c["cwd"], env={**os.environ, **c["env"], "LLVM_PROFILE_FILE": "/dev/null"}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    open(os.path.join(d, "sections.txt"), "w").write(q.stdout)
    info = dict(id=rid, name=c["name"], cwd=c["cwd"], ini=args[args.index("-f") + 1], config=args[args.index("-c") + 1] if "-c" in args else "General",
                run=args[args.index("-r") + 1], exit=p.returncode, verified="Fingerprint successfully verified" in p.stdout, wall=round(wall, 3),
                ned_types=len(ned))
    json.dump(info, open(os.path.join(d, "run.json"), "w"), indent=1)
    print(rid, info["exit"], info["verified"], info["wall"], len(ned), c["name"][:70], flush=True)
