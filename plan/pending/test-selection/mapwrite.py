#!/usr/bin/env python3
# Writes the test map of the test-selection plan (section 8.3 layout, phase 0 prototype) from the
# output of maprun.py, the function table of "llvm-cov export", the "nm --defined-only -A" output
# of all objects and the .d files of the build.
# Usage: mapwrite.py --root INET_ROOT --runs MAPRUN_DIR --export EXPORT_JSON --nm NM_TXT --out MAP_DIR
import argparse, collections, glob, hashlib, json, os, re, shutil, subprocess

ap = argparse.ArgumentParser()
for a in ("--root", "--runs", "--export", "--nm", "--out"):
    ap.add_argument(a, required=True)
ap.add_argument("--commit", default="")
args = ap.parse_args()
root = os.path.realpath(args.root) + "/"
objdir = os.path.join(root, "out", "clang-coverage")

def rel(p):
    p = os.path.realpath(p)
    return p[len(root):] if p.startswith(root) else None

# --- runs ---
runs = {}
for f in sorted(glob.glob(os.path.join(args.runs, "*", "run.json"))):
    r = json.load(open(f))
    runs[r["id"]] = r
all_ids = sorted(runs)
half = len(all_ids) / 2

def run_set(ids):
    ids = sorted(set(ids))
    if len(ids) > half and len(ids) < len(all_ids):
        return {"except": sorted(set(all_ids) - set(ids))}
    if len(ids) == len(all_ids):
        return "all"
    return ids

# --- functions that ran: mangled name -> run ids ---
ran = collections.defaultdict(set)
for rid in all_ids:
    for name in open(os.path.join(args.runs, rid, "functions.txt")).read().split():
        ran[name].add(rid)

# --- emitters: mangled name -> translation units (source paths) ---
emitters = collections.defaultdict(set)
with open(args.nm, errors="replace") as fh:
    for line in fh:
        # <object>:<address> <type> <name>
        obj, _, rest = line.partition(":")
        parts = rest.split()
        if len(parts) == 3 and parts[1] in ("T", "t", "W"):
            tu = obj[len(objdir) + 1:-2] if obj.startswith(objdir) else None
            if tu:
                emitters[parts[2]].add(tu)
def tu_source(tu):
    for ext in (".cc", ".cpp", ".c"):
        if os.path.exists(os.path.join(root, tu + ext)):
            return tu + ext
    return tu + ".cc"
emitters = {k: sorted(tu_source(t) for t in v) for k, v in emitters.items()}

# --- function table from llvm-cov export ---
export = json.load(open(args.export))["data"][0]
table = collections.defaultdict(dict)  # file -> (start, end) -> entry
for f in export["functions"]:
    path = rel(f["filenames"][0])
    if path is None:
        continue
    regions = [r for r in f["regions"] if r[5] == 0]
    start, end = min(r[0] for r in regions), max(r[2] for r in regions)
    name = f["name"].split(";")[-1].split(":")[-1] if not f["name"].startswith("_Z") else f["name"]
    e = table[path].setdefault((start, end), {"mangled": [], "runs": set(), "tus": set()})
    e["mangled"].append(f["name"])
    e["runs"] |= ran.get(f["name"], set())
    e["tus"] |= set(emitters.get(name, []))
# demangle one name for each entry
names = [e["mangled"][0] for file in table.values() for e in file.values()]
plain = [n.split(";")[-1] for n in names]
dem = subprocess.run(["llvm-cxxfilt"], input="\n".join(plain), stdout=subprocess.PIPE, text=True, check=True).stdout.split("\n")
demangled = dict(zip(names, dem))

# --- include table: TU -> project headers, from the .d files ---
included_by = collections.defaultdict(set)
for d in glob.glob(os.path.join(objdir, "**", "*.d"), recursive=True):
    text = open(d, errors="replace").read().replace("\\\n", " ")
    target, _, deps = text.partition(":")
    tu = None
    for dep in deps.split():
        p = rel(dep if os.path.isabs(dep) else os.path.join(root, "src", dep))  # make runs in src/
        if p is None:
            continue
        if tu is None and re.search(r"\.(cc|cpp|c)$", p):
            tu = p
        elif p.endswith(".h"):
            included_by[p].add(tu)

# runs of each TU: the union of the runs of the functions that it emits
tu_runs = collections.defaultdict(set)
for path, entries in table.items():
    for e in entries.values():
        for tu in e["tus"]:
            tu_runs[tu] |= e["runs"]

# --- NED types: declared type -> file, instantiated types -> runs ---
decl_re = re.compile(r"^\s*(?:simple|module|network|channel|moduleinterface|channelinterface)\s+(\w+)", re.M)
ned_file = {}
for nf in glob.glob(os.path.join(root, "**", "*.ned"), recursive=True):
    if "/out/" in nf:
        continue
    text = open(nf, errors="replace").read()
    m = re.search(r"^\s*package\s+([\w.]+)\s*;", text, re.M)
    pkg = m.group(1) if m else ""
    for t in decl_re.findall(text):
        ned_file[(pkg + "." if pkg else "") + t] = rel(nf)
ned_types = collections.defaultdict(lambda: collections.defaultdict(set))
unresolved = collections.Counter()
for rid in all_ids:
    for t in open(os.path.join(args.runs, rid, "ned.txt")).read().split():
        f, outer = ned_file.get(t), t
        while not f and "." in outer:  # a type in the "types:" section of another type
            outer = outer.rsplit(".", 1)[0]
            f = ned_file.get(outer)
        if f:
            ned_types[f][t].add(rid)
        else:
            unresolved[t] += 1

# --- ini sections ---
ini_sections = collections.defaultdict(lambda: collections.defaultdict(set))
for rid, r in runs.items():
    ini = rel(os.path.join(r["cwd"], r["ini"]))
    for s in open(os.path.join(args.runs, rid, "sections.txt")).read().splitlines():
        if s.strip():
            ini_sections[ini][s.strip()].add(rid)

# --- data files from the file trace ---
tracked = set(subprocess.run(["git", "-C", root, "ls-files", "-z"], stdout=subprocess.PIPE, text=True, check=True).stdout.split("\0"))
data = collections.defaultdict(lambda: collections.defaultdict(set))  # path -> kind -> runs
listed = collections.defaultdict(set)
for rid in all_ids:
    walked = set()
    entries = []
    for f in glob.glob(os.path.join(args.runs, rid, "trace.*")):
        for line in open(f, errors="replace"):
            op, ok, p = line.rstrip("\n").split(" ", 2)
            if op in ("openat", "statat", "chdir"):
                continue
            if op == "glob":  # the NED folder walk of omnetpp (FileGlobber "*")
                walked.add(os.path.dirname(os.path.normpath(p)))
                continue
            entries.append((op, ok, os.path.normpath(p)))
    for op, ok, p in entries:
        if ok == "fail":  # a failed lookup: any path in the tree
            if os.path.islink(p):  # a broken link, for example doc/media without the media checkout
                continue
            r = p[len(root):] if p.startswith(root) else None
        else:  # an existing file: only a file of the repository
            r = rel(p)
            if r not in tracked:
                continue
        if r is None or r.startswith("out/") or "/results" in "/" + r or r.endswith(".ned"):
            continue
        if op == "list":
            if ok == "ok":
                listed[r].add(rid)
            else:
                data[r]["lookup"].add(rid)
        elif ok == "fail":
            data[r]["lookup"].add(rid)
        elif op == "open":
            data[r]["read"].add(rid)
        elif os.path.dirname(p) not in walked:
            data[r]["examined"].add(rid)

# --- write ---
shutil.rmtree(args.out, ignore_errors=True)
def dump_lines(obj):
    # one JSON value on each line, so that a git diff shows one function or one key for each line
    parts = []
    for k, v in obj.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            parts.append(json.dumps(k) + ": [\n" + ",\n".join(json.dumps(x, sort_keys=True) for x in v) + "\n]")
        elif isinstance(v, dict):
            parts.append(json.dumps(k) + ": {\n" + ",\n".join(json.dumps(kk) + ": " + json.dumps(vv, sort_keys=True) for kk, vv in sorted(v.items())) + "\n}")
        else:
            parts.append(json.dumps(k) + ": " + json.dumps(v, sort_keys=True))
    return "{\n" + ",\n".join(parts) + "\n}\n"

def write(path, obj, lines=None):
    if path.startswith("/") or ".." in path.split("/"):
        raise RuntimeError(f"path outside the map: {path}")
    full = os.path.join(args.out, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        fh.write(dump_lines(obj) if lines else json.dumps(obj, indent=1, sort_keys=True) + "\n")

folder_use = collections.defaultdict(lambda: collections.defaultdict(set))
def use(path, kind, ids):
    parts = path.split("/")
    for i in range(len(parts)):
        folder_use["/".join(parts[:i])][kind] |= set(ids)

files = collections.defaultdict(dict)
for path, entries in table.items():
    out = []
    for (s, e), x in sorted(entries.items()):
        item = {"lines": [s, e], "name": demangled[x["mangled"][0]][:200]}
        if len(x["mangled"]) > 1:
            item["instances"] = len(x["mangled"])
        if x["runs"]:
            item["runs"] = run_set(x["runs"])
        tus = sorted(x["tus"] - {path})
        if tus:
            item["tus"] = tus if len(tus) <= 20 else {"count": len(tus)}
        out.append(item)
        use(path, "functions", x["runs"])
    files[path]["functions"] = out
for path, ids in tu_runs.items():
    files.setdefault(path, {})["tu_runs"] = run_set(ids)
for path, tus in included_by.items():
    files.setdefault(path, {})["included_by"] = sorted(t for t in tus if t)
for path, types in ned_types.items():
    files[path]["types"] = {t: run_set(ids) for t, ids in sorted(types.items())}
    for ids in types.values():
        use(path, "ned", ids)
for path, sections in ini_sections.items():
    files[path]["sections"] = {s: run_set(ids) for s, ids in sorted(sections.items())}
    for ids in sections.values():
        use(path, "ini", ids)
for path, kinds in data.items():
    files[path]["data"] = {k: run_set(ids) for k, ids in sorted(kinds.items())}
    for ids in kinds.values():
        use(path, "data", ids)
for path, obj in files.items():
    write(path + ".json", obj, lines=True)
for folder, kinds in folder_use.items():
    obj = {k: len(v) for k, v in sorted(kinds.items())}
    if folder in listed:
        obj["listed"] = run_set(listed[folder])
    write(os.path.join(folder, "index.json"), obj)
write("runs.json", {rid: {k: runs[rid][k] for k in ("name", "ini", "config", "run", "exit", "verified")} for rid in all_ids})
write("tests.json", {"fingerprint": {runs[rid]["name"]: [rid] for rid in all_ids}})
write("header.json", {"project": "inet", "commit": args.commit, "runs": len(all_ids), "unresolved_ned_types": dict(unresolved)})
print("files", len(files), "functions", sum(len(v) for v in table.values()), "functions that ran", sum(1 for v in table.values() for e in v.values() if e["runs"]),
      "ned files", len(ned_types), "ini files", len(ini_sections), "data files", len(data), "listed folders", len(listed), "unresolved ned types", len(unresolved))
