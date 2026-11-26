"""
Rule R-NDEBUG of the change-based test selection (see the test selection plan of opp_repl,
``plan/pending/test-selection.md``, section 5.1). The map comes from the coverage build, which does
not define ``NDEBUG``, but some tests run in release mode, which defines it. Code that only a
release build compiles (a release-only block) can call functions and include files that the map
does not record for the runs.

This module finds the release-only blocks of the C++ sources:

- the branch of ``#ifdef NDEBUG`` and the ``#else`` branch of ``#ifndef NDEBUG``, also as
  ``#if defined(NDEBUG)`` and ``#if !defined(NDEBUG)``;
- both branches of a conditional whose expression is not one of these forms but names ``NDEBUG``;
- both branches of a conditional on a macro that a branch of such a conditional defines (for example
  ``CHUNK_CHECK_USAGE_ENABLED``), to a fixed point over all files.

For each block, it gives the names in the block and the project files that the block includes,
also through the includes of these files. The selection uses them: a changed function whose name is
in a block, or a changed file that a block includes, selects the runs of the block.
"""

import collections
import os
import re

__sphinx_mock__ = True # ignore this module in documentation

_CONDITIONAL = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)$")
_DEFINE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)")
_INCLUDE = re.compile(r"^\s*#\s*include\s*\"([^\"]+)\"")
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")

# the words that are not names of functions, types or macros of the project
KEYWORDS = set("""alignas alignof and and_eq asm auto bitand bitor bool break case catch char char8_t char16_t char32_t class compl concept
const consteval constexpr constinit const_cast continue co_await co_return co_yield decltype default delete do double dynamic_cast else enum
explicit export extern false float for friend goto if inline int long mutable namespace new noexcept not not_eq nullptr operator or or_eq
private protected public register reinterpret_cast requires return short signed sizeof static static_assert static_cast struct switch template
this thread_local throw true try typedef typeid typename union unsigned using virtual void volatile wchar_t while xor xor_eq
define undef include ifdef ifndef elif endif error pragma line defined NDEBUG""".split())

def _strip_comments(text):
    return re.sub(r"//.*|/\*.*?\*/", "", text).strip()

# The activity of a branch in one configuration (release or debug) is True, False, None (it depends
# on NDEBUG in a way that is not known), or an expression of the conditions that do not depend on
# NDEBUG. Both configurations make the same expression from the same conditions, so two equal
# expressions mean that the branch is active in both configurations or in neither.

def _not(value):
    if value is True or value is False:
        return not value
    if value is None:
        return None
    return value[1] if value[0] == "not" else ("not", value)

def _and(a, b):
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    if a is True:
        return b
    if b is True or a == b:
        return a
    return ("and", a, b)

def _or(a, b):
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    if a is False:
        return b
    if b is False or a == b:
        return a
    return ("or", a, b)

_CONFIGURATIONS = ("release", "debug")
# the value of NDEBUG: defined in release mode, not defined in the debug and coverage modes
_NDEBUG = {"release": ("defined", "1"), "debug": "undefined"}

def _evaluate(directive, expression, configuration, macros, guard=None):
    # the value of the condition of a directive in one configuration; macros maps a macro that
    # depends on NDEBUG to its value in each configuration: ("defined", text), "undefined" or None;
    # guard is the macro that the first branch of an #ifndef defines
    expression = _strip_comments(expression)
    if directive == "ifdef":
        expression = f"defined({expression})"
    elif directive == "ifndef":
        expression = f"!defined({expression})"
    compact = expression.replace(" ", "")
    match = re.fullmatch(r"(!?)(?:defined\(?([A-Za-z_]\w*)\)?|([A-Za-z_]\w*))", compact)
    names = set(_IDENTIFIER.findall(expression)) - {"defined"}
    if match and match.group(1) and match.group(2) and match.group(2) == guard:
        # a guard such as #ifndef X ... #define X: the build does not define X before
        return True
    if not names & (set(macros) | {"NDEBUG"}):
        return ("condition", compact)
    if not match:
        return None
    name = match.group(2) or match.group(3)
    value = _NDEBUG[configuration] if name == "NDEBUG" else macros.get(name, {}).get(configuration)
    if value is None:
        result = None
    elif match.group(2):
        result = value != "undefined"
    else:
        result = value != "undefined" and value[1].strip() not in ("", "0")
    return _not(result) if match.group(1) else result

def _get_guards(lines):
    # the line number of each #ifndef X or #if !defined(X) whose first branch defines X -> X
    guards = {}
    stack = []
    for number, line in enumerate(lines, 1):
        match = _CONDITIONAL.match(line)
        if match:
            directive, rest = match.groups()
            if directive in ("if", "ifdef", "ifndef"):
                name = re.fullmatch(r"!defined\(?([A-Za-z_]\w*)\)?", _strip_comments(rest).replace(" ", "")) if directive == "if" else None
                stack.append([number, rest.split()[0] if directive == "ifndef" and rest.split() else (name.group(1) if name else None), True])
            elif stack and directive == "endif":
                stack.pop()
            elif stack:
                stack[-1][2] = False
            continue
        match = _DEFINE.match(line)
        if match:
            # also a define inside a nested conditional of the first branch
            for frame in stack:
                if frame[2] and frame[1] == match.group(1):
                    guards[frame[0]] = match.group(1)
    return guards

def _walk_conditionals(text, macros):
    # yields (first line, last line, activity) of each branch of each conditional, with the
    # activity of the branch in each configuration
    guards = _get_guards(text.splitlines())
    stack = [] # (activity of the parent, activity of the branch, any earlier branch taken)
    activity = {configuration: True for configuration in _CONFIGURATIONS}
    start = 0
    for number, line in enumerate(text.splitlines(), 1):
        match = _CONDITIONAL.match(line)
        if not match:
            continue
        directive, rest = match.groups()
        if directive in ("if", "ifdef", "ifndef"):
            condition = {c: _evaluate(directive, rest, c, macros, guards.get(number)) for c in _CONFIGURATIONS}
            branch = {c: _and(activity[c], condition[c]) for c in _CONFIGURATIONS}
            stack.append((activity, branch, condition, start))
            activity, start = branch, number
        elif not stack:
            continue
        else:
            parent, branch, taken, parent_start = stack[-1]
            yield start, number, branch
            if directive == "endif":
                stack.pop()
                activity, start = parent, parent_start
            else:
                condition = {c: True for c in _CONFIGURATIONS} if directive == "else" else {c: _evaluate("if", rest, c, macros) for c in _CONFIGURATIONS}
                branch = {c: _and(parent[c], _and(_not(taken[c]), condition[c])) for c in _CONFIGURATIONS}
                stack[-1] = (parent, branch, {c: _or(taken[c], condition[c]) for c in _CONFIGURATIONS}, parent_start)
                activity, start = branch, number

def _is_release_only(activity):
    release, debug = activity["release"], activity["debug"]
    return release is not False and debug is not True and (release != debug or release is None)

def _differs(activity):
    return activity["release"] != activity["debug"] or activity["release"] is None

def find_release_dependent_macros(texts):
    """
    Returns the macros whose definition depends on ``NDEBUG``, over the texts of all files, as
    ``{name: {"release": value, "debug": value}}``; a value is ``("defined", text)``,
    ``"undefined"`` or None if it is not known.
    """
    macros = {}
    for _ in range(10):
        definitions = collections.defaultdict(list) # name -> [(activity, text)]
        for text in texts:
            lines = text.splitlines()
            for first, last, activity in _walk_conditionals(text, macros):
                if _differs(activity):
                    for line in lines[first:last - 1]:
                        match = re.match(r"^\s*#\s*define\s+([A-Za-z_]\w*)(\(.*?\))?\s*(.*)$", line)
                        if match:
                            definitions[match.group(1)].append((activity, match.group(3)))
        found = {}
        for name, items in definitions.items():
            value = {}
            for configuration in _CONFIGURATIONS:
                active = [text for activity, text in items if activity[configuration] is True]
                unknown = [text for activity, text in items if activity[configuration] is not True and activity[configuration] is not False]
                if unknown or len(set(active)) > 1:
                    value[configuration] = None
                else:
                    value[configuration] = ("defined", active[0]) if active else "undefined"
            found[name] = value
        if found == macros:
            break
        macros = found
    return macros

def find_release_only_blocks(text, macros={}):
    """Returns the ``(first line, last line)`` of each release-only block of a file: the lines of the directives that open and close the branch."""
    return [(first, last) for first, last, activity in _walk_conditionals(text, macros) if _is_release_only(activity)]

def resolve_include(path, include, root_folder, include_folders):
    """Returns the project path of the file of ``#include "include"`` in *path*, or None for a file outside the project."""
    for folder in [os.path.dirname(path), *include_folders]:
        candidate = os.path.normpath(os.path.join(folder, include))
        if os.path.isfile(os.path.join(root_folder, candidate)):
            return candidate
    return None

def scan_release_only_blocks(root_folder, cpp_files, include_folders):
    """
    Returns the release-only blocks of the C++ files *cpp_files* (relative to *root_folder*) as a list
    of ``{"path", "lines", "names", "includes"}``: the names are the identifiers in the block, and
    the includes are the project files that the block includes, also through their includes.
    """
    from opp_repl.test.test_map.select import tokenize_cpp_lines
    texts = {}
    for path in cpp_files:
        with open(os.path.join(root_folder, path), errors="replace") as f:
            texts[path] = f.read()
    candidates = {path: text for path, text in texts.items() if "NDEBUG" in text}
    macros = find_release_dependent_macros(list(candidates.values()))
    if macros:
        pattern = re.compile(r"\b(" + "|".join(sorted(macros)) + r")\b")
        candidates = {path: text for path, text in texts.items() if "NDEBUG" in text or pattern.search(text)}
    include_cache = {}
    def get_includes(path):
        # the project files that path includes, also through their includes
        if path in include_cache:
            return include_cache[path]
        include_cache[path] = set()
        result = set()
        text = texts.get(path)
        if text is None and os.path.isfile(os.path.join(root_folder, path)):
            with open(os.path.join(root_folder, path), errors="replace") as f:
                text = texts[path] = f.read()
        for line in (text or "").splitlines():
            match = _INCLUDE.match(line)
            if match:
                included = resolve_include(path, match.group(1), root_folder, include_folders)
                if included:
                    result.add(included)
                    result |= get_includes(included)
        include_cache[path] = result
        return result
    blocks = []
    for path, text in sorted(candidates.items()):
        lines = text.splitlines()
        tokens = tokenize_cpp_lines(text)
        for first, last in find_release_only_blocks(text, macros):
            names = {token for line_tokens in tokens[first:last - 1] for token in line_tokens if _IDENTIFIER.fullmatch(token) and token not in KEYWORDS}
            # the parameters of a macro are not names of the project
            for line in lines[first:last - 1]:
                match = re.match(r"^\s*#\s*define\s+[A-Za-z_]\w*\(([^)]*)\)", line)
                if match:
                    names -= set(_IDENTIFIER.findall(match.group(1)))
            includes = set()
            for line in lines[first:last - 1]:
                match = _INCLUDE.match(line)
                if match:
                    included = resolve_include(path, match.group(1), root_folder, include_folders)
                    if included:
                        includes.add(included)
                        includes |= get_includes(included)
            blocks.append({"path": path, "lines": [first, last], "names": sorted(names), "includes": sorted(includes)})
    return blocks

def get_simple_function_name(name):
    """Returns the name of a function without its scope, template arguments and parameters, for example ``bar`` for ``inet::Foo<int>::bar(int) const``."""
    end = name.rfind(")")
    if end < 0:
        return name
    depth = 0
    index = end
    while index >= 0:
        if name[index] == ")":
            depth += 1
        elif name[index] == "(":
            depth -= 1
            if depth == 0:
                break
        index -= 1
    head = name[:max(index, 0)].rstrip()
    # the template arguments of the function
    while head.endswith(">"):
        depth = 0
        for position in range(len(head) - 1, -1, -1):
            if head[position] == ">":
                depth += 1
            elif head[position] == "<":
                depth -= 1
                if depth == 0:
                    head = head[:position].rstrip()
                    break
        else:
            break
    match = re.search(r"~?[A-Za-z_]\w*$", head)
    return match.group(0).lstrip("~") if match else head
