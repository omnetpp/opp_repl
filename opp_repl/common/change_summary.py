"""Summarize what a change does to the interface of a simulation project.

Extracts a model of the project's interface from two versions of a source tree, diffs the two
models, and renders a markdown report of what was added, removed, changed, renamed or moved.

The reader is a programmer or a reviewing agent who must answer one question -- what does this
change do to the things other people depend on? -- without reading the diff.

The design is ``plan/pending/change-summary.md``.  Everything here reads sources only: no build
is needed, so a summary is available for a branch that does not compile.
"""

import glob
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict

__sphinx_mock__ = True

# ---------------------------------------------------------------------------
# The fact model
# ---------------------------------------------------------------------------

class Fact:
    """One extracted thing: its kind, its identity, what can change about it, and where it lives."""

    __slots__ = ("kind", "id", "attrs", "origin")

    def __init__(self, kind, id, attrs=None, origin=None):
        self.kind = kind
        self.id = id
        self.attrs = attrs or {}
        self.origin = origin

    def signature(self):
        return tuple(sorted((k, str(v)) for k, v in self.attrs.items()))

    def __repr__(self):
        return f"Fact({self.kind}, {self.id})"

KINDS = [
    ("ned.type",       "NED types"),
    ("ned.parameter",  "NED parameters"),
    ("ned.gate",       "NED gates"),
    ("ned.signal",     "NED signals"),
    ("ned.statistic",  "NED statistics"),
    ("ned.property",   "NED properties"),
    ("msg.type",       "message types"),
    ("msg.field",      "message fields"),
    ("msg.enum.value", "message enum values"),
    ("cpp.class",      "C++ classes"),
    ("cpp.function",   "C++ public functions"),
    ("feature",        "project features"),
    ("folder",         "source folders"),
]
KIND_TITLES = dict(KINDS)

KIND_SINGULAR = {
    "ned.type": "NED type", "ned.parameter": "NED parameter", "ned.gate": "NED gate",
    "ned.signal": "NED signal", "ned.statistic": "NED statistic", "ned.property": "NED property",
    "msg.type": "message type", "msg.field": "message field",
    "msg.enum.value": "message enum value", "cpp.class": "C++ class",
    "cpp.function": "C++ public function", "feature": "project feature", "folder": "source folder",
}

# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------

def _run(args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)

def _relative(path, source_path):
    """A fact's origin must be relative to the source root.

    Two worktrees of the same repository sit at different absolute paths, so an absolute origin
    makes every fact in the tree read as moved.
    """
    if not path:
        return ""
    try:
        return os.path.relpath(os.path.abspath(path), os.path.abspath(source_path))
    except ValueError:
        return path

def _text(node, *names):
    for n in names:
        v = node.get(n)
        if v:
            return v
    return None

def extract_ned_facts(source_path, out_xml):
    """Extract NED facts through ``opp_nedtool``, one call for the whole tree."""
    facts = []
    r = _run(["opp_nedtool", "c", "-x", "-m", "-o", out_xml, source_path])
    if not os.path.exists(out_xml):
        return facts, f"opp_nedtool failed: {r.stderr.strip()[:200]}"
    root = ET.parse(out_xml).getroot()
    for ned_file in root.iter("ned-file"):
        origin = _relative(ned_file.get("filename") or "", source_path)
        package = None
        for pkg in ned_file.iter("package"):
            package = pkg.get("name")
            break
        for tag, kind in (("simple-module", "simple"), ("compound-module", "module"),
                          ("module-interface", "interface"), ("channel", "channel"),
                          ("channel-interface", "channelinterface")):
            for node in ned_file.iter(tag):
                name = node.get("name")
                qname = f"{package}.{name}" if package else name
                extends = ",".join(sorted(e.get("name") for e in node.findall("extends") if e.get("name")))
                like = ",".join(sorted(e.get("name") for e in node.findall("interface-name") if e.get("name")))
                facts.append(Fact("ned.type", qname,
                                  {"kind": kind, "extends": extends, "like": like}, origin))
                _extract_ned_members(node, qname, origin, facts)
    return facts, None

def _extract_ned_members(node, qname, origin, facts):
    for params in node.findall("parameters"):
        for p in params.findall("param"):
            pname = p.get("name")
            # A pattern assignment (``*.mibModule = ...``) is an assignment, not a declaration:
            # it carries no type.  Only a declaration is part of the module's interface.
            if not pname or not p.get("type"):
                continue
            facts.append(Fact("ned.parameter", f"{qname}.{pname}", {
                "type": p.get("type") or "",
                "default": _unparse(p),
                "is-default": p.get("is-default") or "false",
                "volatile": p.get("is-volatile") or "false",
            }, origin))
        for prop in params.findall("property"):
            _extract_ned_property(prop, qname, origin, facts)
    for gates in node.findall("gates"):
        for g in gates.findall("gate"):
            gname = g.get("name")
            if not gname:
                continue
            facts.append(Fact("ned.gate", f"{qname}.{gname}", {
                "type": g.get("type") or "",
                "vector": g.get("is-vector") or "false",
            }, origin))

def _extract_ned_property(prop, qname, origin, facts):
    pname = prop.get("name")
    index = prop.get("index")
    keys = {}
    for k in prop.findall("property-key"):
        kn = k.get("name") or "value"
        vals = [l.get("value") or l.get("text") or "" for l in k.findall("literal")]
        keys[kn] = ",".join(vals)
    if pname == "signal" and index:
        facts.append(Fact("ned.signal", f"{qname}.{index}", {"type": keys.get("type", "")}, origin))
    elif pname == "statistic" and index:
        facts.append(Fact("ned.statistic", f"{qname}.{index}", {
            "source": keys.get("source", ""), "record": keys.get("record", ""),
            "title": keys.get("title", ""), "unit": keys.get("unit", ""),
            "interpolationmode": keys.get("interpolationmode", ""),
        }, origin))
    elif pname and not index and pname not in ("display",):
        facts.append(Fact("ned.property", f"{qname}@{pname}",
                          {"value": ";".join(f"{k}={v}" for k, v in sorted(keys.items()))}, origin))

def _unparse(node):
    """Best-effort text of a parameter's default expression."""
    parts = []
    for lit in node.iter("literal"):
        parts.append(lit.get("value") or lit.get("text") or "")
    for op in node.iter("operator"):
        parts.append(op.get("name") or "")
    for idn in node.iter("ident"):
        parts.append(idn.get("name") or "")
    return " ".join(p for p in parts if p).strip()

def extract_msg_facts(source_path, out_xml):
    """Extract message facts through ``opp_msgtool``, one call for the whole tree."""
    facts = []
    files = sorted(glob.glob(source_path + "/**/*.msg", recursive=True))
    if not files:
        return facts, None
    r = _run(["opp_msgtool", "c", "-x", "-m", "-o", out_xml] + files)
    if not os.path.exists(out_xml):
        return facts, f"opp_msgtool failed: {r.stderr.strip()[:200]}"
    root = ET.parse(out_xml).getroot()
    for msg_file in root.iter("msg-file"):
        origin = _relative(msg_file.get("filename") or "", source_path)
        for tag, kind in (("class", "class"), ("struct", "struct"), ("enum", "enum"),
                          ("message", "message"), ("packet", "packet")):
            for node in msg_file.iter(tag):
                name = node.get("name")
                if not name:
                    continue
                facts.append(Fact("msg.type", name, {
                    "kind": kind, "extends": node.get("extends-name") or "",
                }, origin))
                for f in node.findall("field"):
                    fname = f.get("name")
                    if not fname:
                        continue
                    facts.append(Fact("msg.field", f"{name}.{fname}", {
                        "type": f.get("data-type") or "",
                        "vector": f.get("is-vector") or "false",
                        "default": f.get("default-value") or "",
                    }, origin))
                for e in node.findall("enum-field"):
                    ename = e.get("name")
                    if ename:
                        facts.append(Fact("msg.enum.value", f"{name}::{ename}",
                                          {"value": e.get("value") or ""}, origin))
    return facts, None

# -- the C++ fast tier ------------------------------------------------------

_CLASS = re.compile(r"^\s*(?:template\s*<.*>\s*)?(class|struct)\s+(?:\w+_API\s+)?(\w+)\b(?!.*;\s*$)")
_ACCESS = re.compile(r"^\s*(public|protected|private)\s*:")
# name, arguments, qualifiers, pure-virtual.  The trailing ``(?::[^;{]*)?`` consumes a
# constructor's member-initializer list, which would otherwise force the argument group to
# backtrack across it and swallow the whole list into the signature.
_FUNC = re.compile(r"^\s*(?:(?:virtual|static|inline|explicit|constexpr|friend)\s+)*"
                   r"(?:[\w:<>,\s\*&]+?[\s\*&]+)?(~?\w+)\s*\(([^;{]*?)\)\s*"
                   r"((?:const|override|final|noexcept|&|\s)*)"
                   r"(=\s*0)?\s*(?:=\s*(?:default|delete))?\s*(?::[^;{]*)?[;{]")
_SKIP = {"if", "for", "while", "switch", "return", "sizeof", "catch", "throw", "else", "do"}

def extract_cpp_facts(source_path):
    """The fast C++ tier: an access-aware header scan.

    Indicative, not complete -- a declaration whose arguments span several lines is missed.  The
    misses are systematic, so they largely cancel in a diff; a reformatted declaration does not
    cancel and shows as one removed plus one added.  Generated ``*_m.h`` are excluded, because the
    ``msg.*`` facts already carry that change.
    """
    facts = []
    headers = [f for f in sorted(glob.glob(source_path + "/**/*.h", recursive=True))
               if not f.endswith("_m.h")]
    for fn in headers:
        origin = os.path.relpath(fn, source_path)
        depth = 0
        stack = []          # [name, access, brace_depth, opened, exported, bases]
        for s in _logical_lines(fn):
            m = _CLASS.match(s)
            if m:
                bases = ""
                if ":" in s:
                    bases = " ".join(s.split(":", 1)[1].replace("{", "").split())
                exported = "_API " in s
                stack.append([m.group(2), "private" if m.group(1) == "class" else "public",
                              depth, False, exported, bases])
                if exported or bases:
                    qname = "::".join(e[0] for e in stack)
                    facts.append(Fact("cpp.class", qname,
                                      {"bases": bases, "exported": str(exported)}, origin))
            elif stack:
                top = stack[-1]
                a = _ACCESS.match(s)
                if a:
                    top[1] = a.group(1)
                elif top[3] and top[1] == "public" and depth == top[2] + 1:
                    f = _FUNC.match(s)
                    if f and f.group(1) not in _SKIP:
                        args = _normalize_args(f.group(2))
                        owner = "::".join(e[0] for e in stack)
                        # ``const`` is an attribute, not part of the identity: adding it to an
                        # existing function is a change, not a removal plus an addition.
                        facts.append(Fact("cpp.function", f"{owner}::{f.group(1)}({args})", {
                            "const": str(bool(re.search(r"\bconst\b", f.group(3)))),
                            "virtual": str("virtual" in s.split(f.group(1))[0]),
                            "pure": str(bool(f.group(4))),
                        }, origin))
            opens = s.count("{")
            depth += opens - s.count("}")
            if stack and opens and not stack[-1][3]:
                stack[-1][3] = True
                stack[-1][2] = depth - 1
            while stack and stack[-1][3] and depth <= stack[-1][2]:
                stack.pop()
    return facts, None

def _logical_lines(path):
    """Yield logical lines: a declaration whose parentheses span several lines is joined into one.

    This is what lifts the fast tier's recall.  Without it a multi-line declaration is invisible,
    so a constructor that gains an argument reads as a pure removal -- the new one is never seen.
    """
    buf, depth = "", 0
    for line in open(path, encoding="utf-8", errors="replace"):
        text = line.split("//")[0].rstrip("\n")
        if buf:
            buf += " " + text.strip()
        else:
            buf = text
        depth += buf.count("(") - buf.count(")") if not buf.strip() else 0
        opens, closes = buf.count("("), buf.count(")")
        if opens > closes and len(buf) < 2000:
            continue                       # unbalanced: keep collecting
        yield buf
        buf = ""
    if buf:
        yield buf

def _normalize_args(args):
    """Whitespace-normalize an argument list, and drop the argument names.

    Only the types decide whether two declarations are the same function, and a renamed argument
    must not read as a changed interface.
    """
    out = []
    for a in args.split(","):
        a = a.split("=")[0]                      # drop a default value
        a = " ".join(a.split())
        a = re.sub(r"\s*([*&])\s*", r" \1", a)
        a = re.sub(r"\b\w+$", "", a).strip()     # drop the argument name
        if a:
            out.append(a)
    return ", ".join(out)

def extract_project_facts(root_path):
    """Features from ``.oppfeatures``, and the source folder tree."""
    facts = []
    features_file = os.path.join(root_path, ".oppfeatures")
    if os.path.exists(features_file):
        try:
            root = ET.parse(features_file).getroot()
            for f in root.iter("feature"):
                name = f.get("id") or f.get("name")
                if name:
                    facts.append(Fact("feature", name, {
                        "requires": f.get("requires") or "",
                        "defines": f.get("compileFlags") or "",
                        "nedPackages": f.get("nedPackages") or "",
                    }, ".oppfeatures"))
        except ET.ParseError:
            pass
    src = os.path.join(root_path, "src")
    if os.path.isdir(src):
        for cur, subdirs, _ in os.walk(src):
            for d in subdirs:
                if not d.startswith((".", "_")):
                    facts.append(Fact("folder",
                                      os.path.relpath(os.path.join(cur, d), src), {}, None))
    return facts, None

def extract_all(root_path, scratch, label):
    """Run every extractor over one source tree.  Returns (facts, notes)."""
    facts, notes = [], []
    src = os.path.join(root_path, "src")
    source_path = src if os.path.isdir(src) else root_path
    for fn, args in ((extract_ned_facts, (source_path, os.path.join(scratch, label + "-ned.xml"))),
                     (extract_msg_facts, (source_path, os.path.join(scratch, label + "-msg.xml"))),
                     (extract_cpp_facts, (source_path,)),
                     (extract_project_facts, (root_path,))):
        f, note = fn(*args)
        facts += f
        if note:
            notes.append(note)
    return facts, notes

# ---------------------------------------------------------------------------
# The diff
# ---------------------------------------------------------------------------

RENAME_CAP = 400
RENAME_THRESHOLD = 0.6

class KindDiff:
    def __init__(self, kind):
        self.kind = kind
        self.added, self.removed, self.changed = [], [], []
        self.moved, self.renamed, self.resignatured = [], [], []

    def is_empty(self):
        return not (self.added or self.removed or self.changed or self.moved
                    or self.renamed or self.resignatured)

def diff_facts(base_facts, head_facts, pair_renames=True):
    """Compare two fact sets, one kind at a time."""
    by_kind = defaultdict(lambda: ([], []))
    for f in base_facts:
        by_kind[f.kind][0].append(f)
    for f in head_facts:
        by_kind[f.kind][1].append(f)

    base_members = _member_index(base_facts)
    head_members = _member_index(head_facts)

    diffs, notes = {}, []
    for kind in sorted(by_kind):
        base, head = by_kind[kind]
        b = {f.id: f for f in base}
        h = {f.id: f for f in head}
        d = KindDiff(kind)
        for i in sorted(set(b) & set(h)):
            if b[i].signature() != h[i].signature():
                d.changed.append((b[i], h[i], _attr_changes(b[i], h[i])))
            elif b[i].origin and h[i].origin and b[i].origin != h[i].origin:
                d.moved.append((b[i], h[i]))
        removed = [b[i] for i in sorted(set(b) - set(h))]
        added = [h[i] for i in sorted(set(h) - set(b))]
        if pair_renames and removed and added:
            if len(removed) > RENAME_CAP or len(added) > RENAME_CAP:
                notes.append(f"rename pairing skipped for {kind}: "
                             f"{len(removed)} removed and {len(added)} added exceed the cap of {RENAME_CAP}")
            else:
                removed, added, d.resignatured = _pair_signatures(kind, removed, added)
                removed, added, d.renamed = _pair_renames(kind, removed, added, base_members, head_members)
        d.removed, d.added = removed, added
        diffs[kind] = d
    return diffs, notes

def _attr_changes(before, after):
    out = []
    for k in sorted(set(before.attrs) | set(after.attrs)):
        bv, av = str(before.attrs.get(k, "")), str(after.attrs.get(k, ""))
        if bv != av:
            out.append((k, bv, av))
    return out

def _pair_signatures(kind, removed, added):
    """Pair a removed and an added function that share a name but differ in their arguments.

    A function that gains an argument is one change, not a removal and an unrelated addition a
    hundred lines apart.  Only a kind whose identity carries a call signature qualifies.
    """
    if kind != "cpp.function":
        return removed, added, []
    def basename(fact):
        return fact.id.split("(")[0]
    by_name = defaultdict(list)
    for a in added:
        by_name[basename(a)].append(a)
    pairs, rest, taken = [], [], set()
    for f in removed:
        cands = [c for c in by_name.get(basename(f), []) if id(c) not in taken]
        if len(cands) == 1:
            taken.add(id(cands[0]))
            pairs.append((f, cands[0]))
        else:
            rest.append(f)
    return rest, [a for a in added if id(a) not in taken], pairs

def _pair_renames(kind, removed, added, base_members, head_members):
    """Pair a removed fact with an added one: first by identical attributes, then by contents."""
    pairs = []
    by_sig = defaultdict(list)
    for f in added:
        by_sig[f.signature()].append(f)
    still_removed, taken = [], set()
    for f in removed:
        cands = [c for c in by_sig.get(f.signature(), []) if id(c) not in taken]
        if len(cands) == 1:
            taken.add(id(cands[0]))
            pairs.append((f, cands[0], "identical attributes"))
        else:
            still_removed.append(f)
    still_added = [a for a in added if id(a) not in taken]

    # contents pairing, for a kind that owns members
    if kind in CONTAINER_KINDS:
        base_m, head_m = base_members, head_members
        taken2 = set()
        rest = []
        for f in still_removed:
            bm = base_m.get(f.id, set())
            best, score = None, 0.0
            for a in still_added:
                if id(a) in taken2:
                    continue
                am = head_m.get(a.id, set())
                if not bm or not am:
                    continue
                j = len(bm & am) / len(bm | am)
                if j > score:
                    best, score = a, j
            if best is not None and score >= RENAME_THRESHOLD:
                taken2.add(id(best))
                pairs.append((f, best, f"{int(score * 100)}% of members in common"))
            else:
                rest.append(f)
        still_removed = rest
        still_added = [a for a in still_added if id(a) not in taken2]
    return still_removed, still_added, pairs

CONTAINER_KINDS = {"ned.type", "msg.type", "cpp.class"}

# Which member kind identifies a container, for the contents pairing of a rename.
MEMBER_KINDS = {
    "ned.parameter": "ned.type", "ned.gate": "ned.type",
    "ned.signal": "ned.type", "ned.statistic": "ned.type",
    "msg.field": "msg.type", "msg.enum.value": "msg.type",
    "cpp.function": "cpp.class",
}

def _member_index(facts):
    """Map a container id to the set of its member names, so a rename can be paired by contents.

    A renamed class keeps its members; that overlap is the evidence the report quotes.
    """
    out = defaultdict(set)
    for f in facts:
        owner_kind = MEMBER_KINDS.get(f.kind)
        if not owner_kind:
            continue
        if f.kind == "cpp.function":
            owner, _, member = f.id.rpartition("::")
        elif f.kind == "msg.enum.value":
            owner, _, member = f.id.partition("::")
        else:
            owner, _, member = f.id.rpartition(".")
        if owner and member:
            out[owner].add(member)
    return out

# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def render_markdown(diffs, notes, header):
    lines = [f"# Change summary — {header['title']}", ""]
    lines.append(header["subtitle"])
    lines.append("")

    counts = _headline(diffs)
    lines += ["## In one line", "", counts, ""]

    breaking = [k for k in diffs if diffs[k].removed or diffs[k].changed]
    lines += ["## Breaking — check these first", ""]
    lines += _section("Removed", diffs, lambda d: d.removed, _fmt_plain, empty="_nothing removed_")
    lines += _section("Changed", diffs, lambda d: d.changed, _fmt_changed, empty="_nothing changed in place_")
    lines += _section("Signature changed", diffs, lambda d: d.resignatured, _fmt_resignatured,
                      empty="_no signature changed_")
    lines += _section("Renamed", diffs, lambda d: d.renamed, _fmt_renamed, empty="_nothing renamed_")
    lines += ["## Added", ""]
    lines += _section(None, diffs, lambda d: d.added, _fmt_plain, empty="_nothing added_")
    moved_any = any(diffs[k].moved for k in diffs)
    if moved_any:
        lines += ["## Moved", ""]
        lines += _section(None, diffs, lambda d: d.moved, _fmt_moved, empty="")

    untouched = [KIND_TITLES.get(k, k) for k in sorted(diffs) if diffs[k].is_empty()]
    lines += ["## Not changed", "",
              (" · ".join(untouched) if untouched else "_every kind has a change_"), ""]
    if notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
    return "\n".join(lines)

def _headline(diffs):
    bits = []
    for verb, get in (("added", lambda d: d.added), ("removed", lambda d: d.removed),
                      ("changed", lambda d: d.changed),
                      ("with a changed signature", lambda d: d.resignatured),
                      ("renamed", lambda d: d.renamed), ("moved", lambda d: d.moved)):
        n = sum(len(get(diffs[k])) for k in diffs)
        if n:
            bits.append(f"**{n}** {verb}")
    return ("; ".join(bits) + ".") if bits else "Nothing in the extracted interface changed."

def _section(title, diffs, get, fmt, empty=""):
    out = []
    if title:
        out += [f"### {title}", ""]
    any_rows = False
    for kind, _ in KINDS:
        d = diffs.get(kind)
        if not d:
            continue
        rows = get(d)
        if not rows:
            continue
        any_rows = True
        name = KIND_TITLES.get(kind, kind)
        if len(rows) == 1:
            name = KIND_SINGULAR.get(kind, name)
        body = fmt(rows)
        if len(rows) > 12:
            out += [f"<details><summary><b>{len(rows)} {name}</b></summary>", ""] + body + ["", "</details>", ""]
        else:
            out += [f"**{len(rows)} {name}**", ""] + body + [""]
    if not any_rows and empty:
        out += [empty, ""]
    return out

def _fmt_plain(rows):
    return [f"- `{f.id}`" for f in rows]

def _fmt_changed(rows):
    out = ["| What | Was | Now |", "|---|---|---|"]
    for before, after, changes in rows:
        for k, bv, av in changes:
            out.append(f"| `{before.id}` — {k} | `{bv or '(empty)'}` | `{av or '(empty)'}` |")
    return out

def _fmt_resignatured(rows):
    out = ["| What | Was | Now |", "|---|---|---|"]
    for before, after in rows:
        name = before.id.split("(")[0]
        out.append(f"| `{name}` | `({before.id.split('(', 1)[1]}` | `({after.id.split('(', 1)[1]}` |")
    return out

def _fmt_renamed(rows):
    out = ["| Was | Now | Evidence |", "|---|---|---|"]
    for before, after, why in rows:
        out.append(f"| `{before.id}` | `{after.id}` | {why} |")
    return out

def _fmt_moved(rows):
    out = ["| What | From | To |", "|---|---|---|"]
    for before, after in rows:
        out.append(f"| `{before.id}` | `{before.origin}` | `{after.origin}` |")
    return out
