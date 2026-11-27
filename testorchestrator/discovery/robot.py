"""Robot Framework adapter — bounded `.robot` parser. Supported
syntax: `*** Test Cases ***` section names (column-0 lines),
`[Tags]`, `[Template]`, section headers, native Given/When/Then
steps inside a test (distinct from raw .feature Gherkin — a Robot
GWT case is a normal robot test whose keyword names happen to
start with those words). Executable selectors: file-level suite
path + `--test 'name'` (exact within its suite file; duplicates
across files disambiguated by the suite arg).
Unsupported constructs (resources/variables in tests, task
sections≠test sections, template resolution) → warnings.
"""
from .base import (Item, Result, glob_match, iter_files,
                   read_text_bounded, rel_posix, setting)

KIND = "robot"
SECTIONS = ("*** test cases ***", "*** tasks ***",
            "*** settings ***", "*** keywords ***",
            "*** variables ***", "*** comments ***")
GWT = ("given ", "when ", "then ", "and ", "but ")


def _parse_robot(text, rel, res):
    """Yield (name, line, tags, templated, gwt) per test."""
    in_tests = False
    cur = None
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        low = line.strip().lower()
        if low in SECTIONS:
            in_tests = low in ("*** test cases ***",
                               "*** tasks ***")
            cur = None
            continue
        if low.startswith("***"):
            in_tests = False
            cur = None
            continue
        if not in_tests:
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if raw[0] not in " \t":
            # new test name at column 0
            if cur:
                yield cur
            cur = {"name": line.strip(), "line": i, "tags": [],
                   "templated": False, "gwt": False}
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.lower().startswith("[tags]"):
            cur["tags"] += [t.strip() for t in
                            s[6:].split() if t.strip()]
        elif s.lower().startswith("[template]"):
            cur["templated"] = True
        elif s.lower().startswith(GWT):
            cur["gwt"] = True
    if cur:
        yield cur


def parse(ctx) -> Result:
    res = Result(method="static")
    base = ctx.base
    roots = ctx.fp.test_roots() or ["tests"]
    res.effective["test_roots"] = setting(
        roots, "override" if ctx.fp.test_roots() else "default")
    inc = ctx.fp.include() or ["*.robot"]
    exc = ctx.fp.exclude()
    res.effective["include"] = setting(
        inc, "override" if ctx.fp.include() else "default")
    res.effective["exclude"] = setting(
        exc, "override" if exc else "default")
    found = False
    for root in roots:
        rd = base / root
        if not rd.is_dir():
            res.warnings.append(f"test root {root!r} not found")
            continue
        for p in iter_files(rd, base, res.warnings):
            if p.suffix != ".robot" or not glob_match(p.name, inc):
                continue
            rel = rel_posix(p, base)
            if exc and glob_match(rel, exc):
                continue
            text = read_text_bounded(p, res.warnings, rel)
            if text is None:
                continue
            tests = list(_parse_robot(text, rel, res))
            if not tests:
                continue
            found = True
            res.items.append(Item(
                kind="suite", path=rel, name=p.stem,
                parent=str(p.parent.relative_to(base)),
                node_id=rel, granularity="file", selectable=True,
                tags=f"{len(tests)} tests"))
            for t in tests:
                warn = ""
                if t["templated"]:
                    warn = ("[Template] case — template expansion "
                            "requires native collection")
                    res.needs_native = True
                tags = ",".join(t["tags"])
                if t["gwt"]:
                    tags = (tags + ",GWT-style").strip(",")
                res.items.append(Item(
                    kind="test", path=rel, name=t["name"],
                    parent=p.stem,
                    node_id=t["name"], granularity="test",
                    selectable=True, tags=tags, warnings=warn))
    if not found:
        res.warnings.append("no .robot suites with tests discovered")
    return res
