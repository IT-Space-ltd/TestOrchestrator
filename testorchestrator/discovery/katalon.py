"""Katalon discovery adapter — reproduces the legacy
`gitsync.discover_project` semantics exactly: one `.prj` under the
scope root, `.tc` cases under Test Cases/, `.ts` suites vs
collections by XML root tag under Test Suites/, `.glbl` profile
names under Profiles/. Static only; never executes repo code."""
import json
import xml.etree.ElementTree as ET

from .base import (Item, Result, SKIP_DIRS, MAX_FILE, iter_files,
                   safe_under, rel_posix, setting)

KIND = "katalon"


def _xml_root(path):
    try:
        if path.stat().st_size > MAX_FILE:
            return None, "oversized"
        for _ev, el in ET.iterparse(str(path), events=("start",)):
            return el.tag.split("}")[-1], None
    except Exception as exc:
        return None, f"malformed: {type(exc).__name__}"
    return None, "malformed: empty"


def parse(ctx) -> Result:
    """ctx.base = worktree + subdirectory + project_root (already
    containment-resolved by the caller)."""
    res = Result(method="static")
    base = ctx.base
    res.effective["project_root"] = setting(
        str(ctx.fp.project_root or ""), "override")
    prjs = [p for p in base.rglob("*.prj")
            if not any(part.startswith(".") or part in SKIP_DIRS
                       for part in p.parts)]
    prjs = [p for p in prjs if safe_under(p, base)]
    if not prjs:
        res.warnings.append(
            "no Katalon .prj file found under the bound path — "
            "not a Katalon project root")
        res.effective[".prj detection"] = setting("none found",
                                                  "default")
        return res
    if len(prjs) > 1:
        names = ", ".join(str(p.relative_to(base)) for p in prjs[:5])
        res.warnings.append(
            f"multiple .prj files — select one explicitly: {names}")
        res.effective[".prj detection"] = setting(
            f"ambiguous ({len(prjs)})", "default")
        return res
    root = prjs[0].parent
    res.effective[".prj root"] = setting(
        str(root.relative_to(base)), "config")

    for p in iter_files(root / "Test Cases", base, res.warnings):
        if p.suffix != ".tc":
            continue
        res.items.append(Item(
            kind="case", path=rel_posix(p, root), name=p.stem,
            parent=rel_posix(p.parent, root), selectable=False,
            granularity="case"))

    for p in iter_files(root / "Test Suites", base, res.warnings):
        if p.suffix != ".ts":
            continue
        tag, warn = _xml_root(p)
        if warn:
            res.warnings.append(f"{rel_posix(p, root)}: {warn}")
        kind = "collection" if tag == "TestSuiteCollectionEntity" \
            else "suite"
        members, dynamic = [], False
        if tag:
            try:
                r = ET.parse(str(p)).getroot()
                if kind == "suite":
                    members = [t.text.strip() for t in r.findall(
                        ".//testCaseLink/testCaseId") if t.text]
                    explicit = bool(r.findall(".//testCaseRunType"))
                    hint = "dynamic" in (r.findtext("name") or "").lower()
                    dynamic = explicit
                    if hint and not explicit:
                        warn = (warn or "") + \
                            " name suggests dynamic (unverified)"
                else:
                    members = [t.text.strip() for t in r.findall(
                        ".//TestSuiteRunConfiguration/testSuiteEntity")
                        if t.text]
            except Exception:
                warn = (warn or "") + " members unparseable"
        res.items.append(Item(
            kind=kind, path=rel_posix(p, root), name=p.stem,
            parent=rel_posix(p.parent, root), members=members,
            dynamic=dynamic, warnings=warn or "",
            granularity="file", selectable=True))

    for p in iter_files(root / "Profiles", base, res.warnings):
        if p.suffix == ".glbl":
            res.items.append(Item(
                kind="profile", path=rel_posix(p, root), name=p.stem,
                selectable=False, granularity="case"))

    res.items.sort(key=lambda i: (i.kind, i.path))
    return res


# serialize for DiscoveredItem rows
def member_json(item: Item) -> str:
    return json.dumps(item.members or [])
