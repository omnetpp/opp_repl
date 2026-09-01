# The change summary

> **Status:** phases 1 to 3 prototyped and applied to INET pull request #1144 · **Owner:** opp_repl · **Documents:** `doc/change_summary.md`, and a procedure in the INET project documentation

A tool that reads two versions of a simulation project and writes a **markdown report of what
changed in its interface**: which modules, parameters, signals, statistics, message types, classes,
public functions and build features were added, removed, changed, renamed or moved.

The reader is a programmer or a reviewing agent who must answer one question — *what does this change
do to the things other people depend on?* — without reading the diff.

## 1. Why

A `git diff` shows lines. It does not show that a parameter lost its default, that a signal was
renamed, that a public function gained an argument, or that a module moved to another package. To
find those a reader walks the whole diff, and an agent spends its context doing it.

Pull request #1144 of INET is 14 commits, 92 files, +8776 and −482 lines. Reading that diff costs an
agent well over a hundred thousand tokens and still gives no reliable answer, because the answer is
spread across the files and the reader must hold it all at once.

**Extract the interface from each side, diff the two extracts, and print a page.** The extraction is
mechanical, so a program does it once and cheaply; the reader gets the conclusion.

## 2. What exists today

`opp_repl/common/summary.py` — 182 lines, nine collectors, and
`print_changes(from_simulation_project, to_simulation_project)`. It collects features, folders,
modules, parameters, signals, statistics, chunks, tags and C++ classes, and it prints what was added
and what was removed.

The shape is right. Four things limit it:

**A collector returns a flat list of names.** The only comparison a set of names allows is *in one
side and not the other*. So the tool can say added and removed, and it can never say **changed** or
**renamed** — which are the two answers a reviewer wants most. A renamed module appears as one
removal and one addition, twenty lines apart.

**`collect_parameters` runs `opp_nedtool` once per NED file**, and writes then deletes an XML file
beside each source. INET has 1262 NED files. Measured, the same conversion with `-m` over the whole
tree is **one call and 0.172 seconds** (§5).

**Everything else is a regular expression over the source**, so it sees less than the real parser
gives away for free: a parameter's type, unit and default; a signal's type; a statistic's source and
record modes; a message field's data type.

**The output is `print`.** It is not a document, it cannot be attached to a pull request, and it
cannot be read by a tool.

Nothing below throws that file away. It becomes the fact-kind registry of §4.

## 3. The fact model

Every extracted thing is one **fact**, and a fact has four parts:

| Part | Means | Example |
| --- | --- | --- |
| `kind` | which registry it belongs to | `ned.parameter` |
| `id` | the stable identity, which decides *same thing* | `EthernetMac.address` |
| `attrs` | the properties that can change under a stable id | `{type: string, default: "auto", volatile: false}` |
| `origin` | the file, and the line where known | `linklayer/ethernet/EthernetMac.ned:41` |

That one shape makes the whole comparison mechanical, and it is the entire reason the tool can report
more than *added* and *removed*:

```
added    id in head only
removed  id in base only
changed  id in both, attrs differ    → and the report names which attribute
renamed  a removed and an added whose attrs match (§6)
moved    same id, different origin
```

`attrs` decides how sensitive the report is. Put a property in `attrs` and a change to it is
reported; leave it out and it is invisible. That choice is the design, and §4 makes it per kind.

**A fact carries no line content.** The report says *the default of `EthernetMac.address` changed
from `"auto"` to `""`*, never a diff hunk. A reader who wants the hunk has the commit.

## 4. The fact kinds

What is extracted, what identifies it, and what counts as a change to it.

### From the NED sources — `opp_nedtool c -x -m`

| Kind | `id` | `attrs` |
| --- | --- | --- |
| `ned.type` | `package.Name` | kind (simple, module, network, interface, channel), `extends`, `like` interfaces, abstract |
| `ned.parameter` | `Type.name` | data type, unit, default value, volatile |
| `ned.gate` | `Type.name` | direction, vector |
| `ned.signal` | `Type.name` | type, unit |
| `ned.statistic` | `Type.name` | source, record modes, title, unit, interpolation |
| `ned.submodule` | `Type.name` | type or `like` type, vector, condition |
| `ned.property` | `Type@name` | value |
| `ned.package` | `package` | — existence only |

### From the message sources — `opp_msgtool c -x -m`

| Kind | `id` | `attrs` |
| --- | --- | --- |
| `msg.type` | `namespace::Name` | kind (class, struct, packet, enum), `extends` |
| `msg.field` | `Type.field` | data type, array, default value, properties |
| `msg.enum.value` | `Enum::VALUE` | numeric value |

`chunks` and `tags` of today's `summary.py` are not separate kinds. They are a `msg.type` whose name
matches the INET role suffix, and the report groups them under that heading — the naming rules
already say what a `*Header`, `*Tag`, `*Req` and `*Ind` is.

### From the C++ headers

| Kind | `id` | `attrs` |
| --- | --- | --- |
| `cpp.class` | `namespace::Name` | base classes, exported (`INET_API`), abstract |
| `cpp.function` | `Class::name(normalized args)` | return type, const, virtual, pure virtual, static, default arguments |

**Only the public surface.** A protected or private member is not something another model depends on,
and reporting it drowns the report in noise.

**Generated headers are excluded.** `*_m.h` and `*_m.cc` are produced from a `.msg`, and the `msg.*`
kinds already carry that change. Measured: the generated headers are 11 % of INET's header files and
**41 % of the public functions found in them** (8838 of 21357). Without the exclusion, one added
message field appears as a dozen new C++ functions, and the C++ section becomes unreadable exactly
when a message changes.

### From the project files

| Kind | `id` | `attrs` | Source |
| --- | --- | --- | --- |
| `feature` | feature id | description, required features, defines, NED packages, source folders | `.oppfeatures` |
| `folder` | path under `src/` | — existence only | tree walk |
| `example` | path under `examples/`, `showcases/`, `tutorials/` | — existence only | tree walk |
| `test` | `category/name` | — existence only | tree walk |
| `ini.config` | `file:[Config Name]` | `extends` | ini scan |

A feature is worth more attention than its size suggests: a feature id becomes a `-DINET_WITH_*`
compile flag and a line in somebody's build script, so adding, renaming or re-scoping one is a change
to a published interface.

## 5. What the measurements say

Measured on 2026-09-01 against `inet-master`, whole tree, one machine.

| Extractor | How | Time | What it yields |
| --- | --- | ---: | --- |
| NED | `opp_nedtool c -x -m -o ned.xml src/inet` | **0.172 s** | 1262 NED files, 4381 parameters, 5838 properties, 1021 gates — the real parser's AST |
| MSG | `opp_msgtool c -x -m -o msg.xml <files>` | **0.037 s** | 761 classes, 2605 fields, 951 enum values, with data types and base classes |
| C++, fast | access-aware header scan, 60 lines of Python | **0.18 s** | 12519 public member functions, generated headers excluded |
| C++, accurate | `doxygen` XML over `src/inet` | **3 m 33 s**, 502 MB | 4375 classes, 39988 public member functions |

Three conclusions follow, and they decide the design.

**NED and MSG are free, and they are authoritative.** One call each, a fifth of a second together,
and the output is the AST of the language's own parser rather than a guess from a regular expression.
There is no reason to run anything else, and no reason to make them optional.

**The C++ side is the only real trade-off.** The fast scan reaches about half of what doxygen sees,
in one nine-hundredth of the time. Its misses are **systematic** — chiefly a declaration whose
arguments span several lines — and a systematic miss mostly cancels in a *diff*, because both sides
miss the same shapes. It does not cancel when a declaration is reformatted: the scan then reports one
function removed and one added, and both are false.

So the fast scan is the default and the report labels the C++ function section **indicative**;
doxygen is opt-in, and its result is cached by commit hash, because a base commit is usually
`origin/master` and is re-used across many summaries.

**The report must not need a build.** Everything above reads sources. That keeps a summary available
for a branch that does not compile, which is exactly when a reviewer wants one.

## 6. Renamed, and moved

A rename is the answer that costs a reviewer most to find by hand, and the one a set of names cannot
give at all.

After the added and removed sets are known, and **within one kind only**:

1. **Moved** — the same `id` with a different `origin`. Report as moved, not as removed and added.
2. **Renamed, exactly** — one removed and one added whose `attrs` are identical. A parameter that
   keeps its type, unit and default, and whose owner is unchanged, is the same parameter under a new
   name. Pair them.
3. **Renamed, by contents** — for a container kind. Two classes are the same class under a new name
   when the sets of their public function names overlap far enough; the same test pairs a NED type by
   its parameters, gates and signals, and a message type by its fields. Use Jaccard overlap with a
   stated threshold, and report the pair as *renamed, probably* with the overlap value, so a reader
   can judge it.
4. Anything left over stays added or removed.

Two rules keep it honest. **A pairing is reported with its evidence**, never as a bare claim. And
**pairing is capped**: when a kind has more than a few hundred unpaired facts on both sides, the step
is skipped with a line saying so, rather than running an expensive match nobody asked for.

## 7. The report

One markdown document, ordered by **what a reviewer must check first**, not by what is easiest to
extract.

```markdown
# Change summary — inet, origin/master..HEAD

`f07d0e766` … `3be545a22`, merge base `f07d0e766`, 14 commits, 92 files.
Extracted 2026-09-01. C++ functions from the fast scan (indicative).

## In one line

12 NED types, 34 parameters, 6 signals and 1 feature added; 2 parameters changed;
1 module renamed; nothing removed.

## Breaking — check these first

### Removed
_none_

### Changed
| What | Was | Now |
|---|---|---|
| `EthernetMac.address` (parameter) | default `"auto"` | default `""` |
| `Ieee80211Mac::sendUp(Packet*)` (function) | non-virtual | virtual |

### Renamed
| Was | Now | Evidence |
|---|---|---|
| `Ieee80211HtMac` | `Ieee80211HighThroughputMac` | identical parameters, gates and signals |

## Added
<details><summary>12 NED types</summary>

…
</details>

## Moved
| What | From | To |
|---|---|---|

## Not changed
NED gates · statistics · features · tests
```

Five properties the format must have:

- **Removed and changed come before added.** A removal breaks somebody; an addition breaks nobody.
- **A long list folds.** `<details>` keeps the page readable when a branch adds two hundred facts.
- **Absence is stated.** The *Not changed* line means the tool looked and found nothing, which a
  reader cannot infer from a missing section.
- **The order is deterministic.** Every list is sorted, so two reports of the same change are
  identical files and a report is itself diffable.
- **The header states what it does not know** — which C++ tier ran, and whether any pairing step was
  capped.

## 8. The interface

### Python

```python
summarize_changes(from_simulation_project, to_simulation_project, **kwargs) -> ChangeSummary
summarize_changes_between_commits(simulation_project=None, git_hash_1=None, git_hash_2=None,
                                  merge_base=True, delete_worktree=False, **kwargs)
```

The second follows `compare_simulations_between_commits` exactly — the same parameter names, the same
worktree handling through `make_worktree_simulation_project`, the same `delete_worktree`. That
function already exists and already does the hard part.

`merge_base=True` is the default and it matters: for a branch, the base is **the merge base with the
target, not the target's tip**. Against the tip, every change somebody else landed in the meantime
appears in the report as your change.

`ChangeSummary` carries the facts and renders on demand: `.to_markdown()`, `.to_json()`,
`.is_empty()`. JSON so that a later gate can assert *this change adds no public function*.

### Command line

```bash
opp_summarize_changes --from origin/master --to HEAD --output summary.md
opp_summarize_changes --pr 1144                     # resolves the merge base itself
opp_summarize_changes --from HEAD~1 --to HEAD --kinds ned,msg --accurate-cpp
```

### MCP

One tool, `summarize_changes`, taking the two refs and the kind filter, returning the markdown. This
is the point of the whole exercise: an agent calls one tool and reads one page.

## 9. What it costs

| | Tokens the agent reads |
| --- | ---: |
| the diff of PR #1144 (9258 changed lines) | of the order of 100 000, estimated |
| this report | of the order of 1 000, estimated |

Both figures are estimates from the line counts, not measurements. The ratio is the point, and the
ratio is not sensitive to the estimate.

The extraction is a few hundred milliseconds of parsing, done by a program that spends no tokens at
all. The agent spends its context on judgment instead of on reconstruction — which is the work it is
actually good at.

## 10. Where the documentation goes

Two documents, because there are two readers, and neither repeats the other.

**`opp_repl/doc/change_summary.md`** — the reference: the fact kinds, the Python API, the command
line, the MCP tool, the options, and the limits. It follows the house style of
`doc/comparing_simulations.md` and is registered in `README.md` beside it.

**`inet-master/doc/project/guide/summarize-a-change.md`** — the procedure for a reviewer or an agent
working on INET: how to get a summary, how to read it, and what to do with what it finds. It is cited
from `guide/review-a-pull-request.md` as the first step, before the `PR-*` checks, because the
architectural surface of a change is what those checks need named.

The split follows the rule INET's document set already states: the tool's reference lives with the
tool, and the procedure lives where the work happens.

## 11. The work

**Phase 1 — the fact model and the two free extractors.** The `Fact` record, the registry, and the
NED and MSG extractors over the merged XML. The diff engine with added, removed, changed and moved.
Markdown rendering. This alone replaces everything `summary.py` does today, and it is the phase that
carries the measured 0.2 seconds.

**Phase 2 — the C++ fast tier.** The access-aware header scan, generated files excluded, signatures
normalized. The section is labelled indicative.

**Phase 3 — renames.** Exact-attribute pairing, then contents pairing with a threshold and a cap.

**Phase 4 — the project files.** Features, folders, examples, tests, ini configs.

**Phase 5 — the interface.** `summarize_changes_between_commits`, the `bin/opp_summarize_changes`
script, and the MCP tool.

**Phase 6 — the accurate C++ tier.** Doxygen XML behind `--accurate-cpp`, cached by commit hash.

**Phase 7 — the documents**, and the retirement of `summary.py` into the new registry.

Phases 1 and 5 are what make the tool usable at all. Everything after 2 raises the quality of the
answer without changing how it is called.

## 12. Open questions

1. **Does it belong to opp_repl, or to INET?** It is written here because opp_repl owns
   `SimulationProject`, the worktree helpers and the MCP surface. But every fact kind above is an
   OMNeT++ or an INET concept, and a second model library would want the same tool. Keep the
   extractors project-agnostic and the role-suffix grouping in a table INET can supply.
2. **Should the C++ tier default to accurate in CI?** Three and a half minutes twice is seven
   minutes, which is nothing in CI and far too much at a prompt. The default may need to differ by
   caller rather than be one value.
3. **How much of a `.ned` expression counts as an attribute?** A parameter default that changes from
   `10ms` to `20ms` is worth reporting. A default that changes from `parent.foo` to `parent.foo `
   is not. Normalize expressions through the parser's own unparse, not by string comparison.
4. **Is `ini.config` in scope?** It is where a study's parameters live, so a changed config is a
   changed result. But `examples/` and `showcases/` hold thousands of them, and the report may
   drown. Perhaps only configs under `tests/`.

## 13. What the first real run found

`opp_repl/common/change_summary.py` implements phases 1 to 3 — the fact model, the NED, message,
C++ and project extractors, the diff, the rename pairing and the markdown renderer. It was run
against INET pull request #1144, base `f07d0e7662` (the merge base), head `3be545a22f`, 14 commits
and 92 files. The report is committed at
`inet/doc/project/audit/report/pull-request/pr-1144-summary.md`.

**It cost 1.2 seconds** to extract 27 761 facts from the base and 27 861 from the head, and 0.11 s
to diff them. The whole run, including two git worktrees, is under three seconds.

**The report is 172 lines.** The diff is 9258 changed lines.

### The eight defects it exposed

A design is a guess until it runs on something real. Eight defects surfaced on the first two runs,
and every one of them would have made the report wrong rather than merely incomplete.

| # | What went wrong | The fix |
| --- | --- | --- |
| 1 | **Every fact read as moved.** `opp_nedtool` writes an absolute `filename` into its XML, and two worktrees of one repository sit at different absolute paths. The first report was 13 516 lines, of which 13 287 were false moves. | `origin` is relative to the source root |
| 2 | A NED **pattern assignment** (`*.mibModule = ...`) was extracted as a parameter declaration | only a `param` that carries a `type` is a declaration |
| 3 | A constructor's **member-initializer list** was swallowed into the signature: `Ieee80211MgmtSta() : host(nullptr), numChannels(-1), …` | the pattern consumes `(?::[^;{]*)?` before the body |
| 4 | A **nested class lost its owner**, so `Result::getStatus` and `ICallback::handlePacketDropped` were ambiguous | the identity is qualified by every enclosing class |
| 5 | Adding `const` to a function read as **one removal plus one addition** | `const` is an attribute, not part of the identity |
| 6 | A **multi-line declaration was invisible**, so a constructor that gained arguments read as a pure removal — the new one was never seen | logical lines: an unbalanced `(` joins the next line |
| 7 | A function whose **arguments changed** appeared as a removal and an addition 130 lines apart | `_pair_signatures`: same `Class::name`, different arguments, is one *signature changed* row |
| 8 | `**1 NED signals**` | a singular title per kind |

Defect 1 is the instructive one. It is not a parsing mistake; it is the design's own §3 statement —
*`origin` is the file* — meeting the fact that a worktree has a path. Nothing in the design was
wrong, and the report was still useless until it was fixed.

Defects 5, 6 and 7 together are what turn the report from a list into an answer. Before them the
headline for #1144 read *102 added, 4 removed*; after them it reads **100 added, 5 changed, 1
signature changed, nothing removed** — which is the truth about a purely additive pull request, and
the opposite of what a reviewer would have concluded from *4 removed*.

### What it got right without being told

Two things in the report are findings a reviewer had to work for.

**The shared-component change.** `IPacketQueue::ICallback` and
`CompoundPacketQueueBase::setPacketDropCallback` appear under *added C++ classes and functions*, and
`Dcf` and `Hcf` appear under *changed* because they gained `public queueing::IPacketQueue::ICallback`
as a base. That is finding F-1 of the rule audit `pr-1144.md` — a queueing capability landing inside
an 802.11 commit, which `PR-SPLIT-UPSTREAM` exists for. The summary surfaces it from the interface
alone, with no knowledge of the commit structure.

**The whole HT surface, grouped.** 4 message types, 29 message fields, 8 NED parameters, 1 NED
signal and 52 C++ functions, each named, in one page.

### What is still missing

- **Phase 4 is partly done**: features and folders are extracted; examples, tests and ini configs
  are not.
- **Phase 5 is not started**: there is no `summarize_changes_between_commits`, no
  `bin/opp_summarize_changes`, and no MCP tool. The prototype is driven by a script.
- **The C++ tier does not expand macros.** A declaration built by a macro is invisible to it. That
  is the honest limit of the fast tier and the reason the report says *indicative*.
- **`_unparse` is a best-effort join**, not the parser's own unparse, so a changed parameter default
  is reported by an approximation of its text. Open question 3 stands.
