# Compares the INET paths of the strace and the LD_PRELOAD trace of each run: files that the run
# opened or examined, and folders that it listed or entered.
import collections, glob, json, os, re  # run in the folder of measure.py: compares out/<i>/strace.txt with out/<i>/preload.*
root = "/home/levy/workspace/inet-coverage-more-suites"
cmds = json.load(open("commands.json"))
line_re = re.compile(r'^(\d+)\s+(\w+)\((?:(AT_FDCWD|\d+), )?"([^"]*)"(.*?)\)\s+= (-?\d+)')
def strace_paths(path, cwd0):
    cwd = collections.defaultdict(lambda: cwd0); used = set(); listed = set()
    for l in open(path, errors="replace"):
        m = line_re.match(l)
        if not m: continue
        pid, call, dirfd, p, rest, ret = m.groups()
        if dirfd not in (None, "AT_FDCWD") or call in ("execve", "getcwd"): continue
        full = os.path.normpath(p if p.startswith("/") else os.path.join(cwd[pid], p))
        if call == "chdir":
            if ret == "0": cwd[pid] = full
            listed.add(full); continue
        (listed if "O_DIRECTORY" in rest else used).add(full)
    return used, listed
def preload_paths(pattern):
    used = set(); listed = set()
    for f in glob.glob(pattern):
        for l in open(f, errors="replace"):
            op, ok, p = l.rstrip("\n").split(" ", 2)
            if op in ("openat", "statat"): continue
            p = os.path.normpath(p)
            if op == "glob": listed.add(os.path.dirname(p))
            elif op in ("list", "chdir"): listed.add(p)
            else: used.add(p)
    return used, listed
inside = lambda s: {x for x in s if x.startswith(root + "/")}
summary = collections.Counter(); examples = collections.Counter()
for i, c in enumerate(cmds):
    su, sl = map(inside, strace_paths(f"out/{i}/strace.txt", c["cwd"]))
    pu, pl = map(inside, preload_paths(f"out/{i}/preload.*"))
    summary["strace files"] += len(su); summary["preload files"] += len(pu)
    summary["strace folders"] += len(sl); summary["preload folders"] += len(pl)
    for x in su - pu: summary["files only strace"] += 1; examples["file " + os.path.relpath(x, root)] += 1
    for x in pu - su: summary["files only preload"] += 1; examples["file+ " + os.path.relpath(x, root)] += 1
    for x in sl - pl: summary["folders only strace"] += 1; examples["folder " + os.path.relpath(x, root)] += 1
    for x in pl - sl: summary["folders only preload"] += 1; examples["folder+ " + os.path.relpath(x, root)] += 1
print(dict(summary)); print(examples.most_common(10))
