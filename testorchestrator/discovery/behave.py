"""Behave adapter — static Gherkin parse of feature_roots plus
step-definition inventory of stepdef_roots. Executable selectors:
file-level `path` and scenario `path:LINE` (behave's native
selector — exact, disambiguates duplicate names by line).
Scenario-outline examples expansion requires native dry-run and is
a candidate, not selectable."""
from .base import Item, Result, glob_match, iter_files, \
    read_text_bounded, rel_posix, setting
from . import gherkin

KIND = "behave"


def _stepdefs(base, roots, warnings):
    """Count step defs under stepdef_roots — informational only
    (step matching is separate from scenario→run binding and is not
    claimed as validated)."""
    import re
    n = 0
    pat = re.compile(r"@(given|when|then|step)\(")
    for r in roots:
        rd = base / r
        if not rd.is_dir():
            continue
        for p in iter_files(rd, base, warnings):
            if p.suffix != ".py":
                continue
            t = read_text_bounded(p, warnings)
            if t:
                n += len(pat.findall(t))
    return n


def parse(ctx) -> Result:
    res = Result(method="static")
    base = ctx.base
    roots = ctx.fp.feature_roots() or ctx.fp.test_roots() or \
        ["features"]
    src = ("override" if ctx.fp.feature_roots()
           else "override" if ctx.fp.test_roots() else "default")
    res.effective["feature_roots"] = setting(roots, src)
    exc = ctx.fp.exclude()
    res.effective["exclude"] = setting(
        exc, "override" if exc else "default")
    found = False
    for root in roots:
        rd = base / root
        if not rd.is_dir():
            res.warnings.append(f"feature root {root!r} not found")
            continue
        for p in iter_files(rd, base, res.warnings):
            if p.suffix != ".feature":
                continue
            rel = rel_posix(p, base)
            if exc and glob_match(rel, exc):
                continue
            text = read_text_bounded(p, res.warnings, rel)
            if text is None:
                continue
            found = True
            feat = gherkin.parse_feature(text, rel)
            res.warnings += feat["warnings"]
            res.items.append(Item(
                kind="suite", path=rel,
                name=feat["title"] or p.stem,
                parent=str(p.parent.relative_to(base)),
                node_id=rel, granularity="file", selectable=True,
                tags=",".join(feat["tags"])))
            for s in feat["scenarios"]:
                tags = ",".join(s["tags"])
                if s["outline"]:
                    res.items.append(Item(
                        kind="scenario", path=rel, name=s["name"],
                        parent=feat["title"] or p.stem,
                        node_id=f"{rel}:{s['line']}",
                        granularity="scenario", selectable=True,
                        tags=tags,
                        warnings="outline — examples expansion "
                                 "needs native dry-run"))
                    res.needs_native = True
                else:
                    res.items.append(Item(
                        kind="scenario", path=rel, name=s["name"],
                        parent=feat["title"] or p.stem,
                        node_id=f"{rel}:{s['line']}",
                        granularity="scenario", selectable=True,
                        tags=tags))
    sd = ctx.fp.stepdef_roots()
    res.effective["stepdef_roots"] = setting(
        sd, "override" if sd else "default")
    n = _stepdefs(base, sd, res.warnings)
    if found and not n:
        res.warnings.append(
            "no step definitions found under step roots — scenarios "
            "will fail at run time (steps unmatched)")
    if not found:
        res.warnings.append("no .feature files discovered")
    return res
