"""Playwright Test (JS/TS) adapter — literal config extraction +
spec-file listing. `testDir`, `testMatch`/`testIgnore`, `projects:
[{name}]` read literally; computed/imported config → 'unresolved
statically' warning, no silent defaults. File-level selection is
exact (`npx playwright test <file> --project=X`); per-test
selection via --grep is NOT exact (substring matching) so
test-level items are candidates only."""
import re
from .base import (Item, Result, glob_match, iter_files,
                   read_text_bounded, rel_posix, setting)
from .cypress import _literal

KIND = "playwright"
CFG_NAMES = ["playwright.config.ts", "playwright.config.js",
             "playwright.config.mts", "playwright.config.mjs"]
DEFAULT_MATCH = ["**/*.@(spec|test).?(c|m)[jt]s?(x)"]


def _projects(text):
    """Literal project names — `name: 'x'` inside projects:[...]."""
    m = re.search(r"projects\s*:\s*\[(.*?)\]", text, re.S)
    if not m:
        return []
    return re.findall(r"name\s*:\s*[\"']([^\"']+)[\"']", m.group(1))


def parse(ctx) -> Result:
    res = Result(method="static")
    base = ctx.base
    cfg_rel = ctx.fp.config_file
    cfg_text, cfg_src = None, ""
    cands = [base / cfg_rel] if cfg_rel else \
        [base / c for c in CFG_NAMES]
    for p in cands:
        if p.is_file():
            cfg_text = read_text_bounded(p, res.warnings, p.name)
            cfg_src = str(p.relative_to(base))
            break

    test_dir = ""
    match = ctx.fp.include()
    ignore = ctx.fp.exclude()
    match_src = "override" if match else "default"
    projects = []
    if cfg_text is not None:
        res.effective["config_file"] = setting(cfg_src, "config")
        td = _literal(cfg_text, "testDir")
        if td:
            test_dir = td[0]
        tm = _literal(cfg_text, "testMatch")
        if tm and not match:
            match, match_src = tm, "config"
        ti = _literal(cfg_text, "testIgnore")
        if ti and not ignore:
            ignore = ti
        projects = _projects(cfg_text)
        dyn = [k for k in ("testDir", "testMatch")
               if re.search(k + r"\s*:\s*[A-Za-z_$]", cfg_text)]
        if dyn:
            res.warnings.append(
                f"{cfg_src}: {', '.join(dyn)} dynamic — unresolved "
                "statically; explicit overrides/roots used")
    elif cfg_rel:
        res.warnings.append(
            f"configured config {cfg_rel!r} not found")

    roots = ctx.fp.test_roots() or ([test_dir] if test_dir else ["."])
    res.effective["testDir"] = setting(
        roots, "override" if ctx.fp.test_roots()
        else "config" if test_dir else "default")
    if not match:
        match = DEFAULT_MATCH
        match_src = "default"
    res.effective["testMatch"] = setting(match, match_src)
    res.effective["testIgnore"] = setting(ignore, "config"
                                          if ignore else "default")
    res.effective["projects"] = setting(
        projects or ctx.fp.settings().get("projects", []),
        "config" if projects else "default")

    matched = False
    for root in roots:
        rd = base if root in (".", "") else base / root
        if not rd.is_dir():
            res.warnings.append(f"testDir {root!r} not found")
            continue
        for p in iter_files(rd, base, res.warnings):
            rel = rel_posix(p, base)
            if p.suffix.lstrip(".") not in ("js", "ts", "jsx", "tsx",
                                            "mts", "cts", "mjs", "cjs"):
                continue
            if not glob_match(rel, match):
                continue
            if ignore and glob_match(rel, ignore):
                continue
            matched = True
            res.items.append(Item(
                kind="suite", path=rel, name=p.stem,
                parent=str(p.parent.relative_to(base)),
                node_id=rel, granularity="file", selectable=True,
                members=projects,
                tags=("projects:" + ",".join(projects)
                      if projects else "")))
    if not matched:
        res.warnings.append(
            "no spec files matched testMatch — check testDir/patterns")
    return res
