"""Jest adapter — literal configuration only (jest.config.* and
the package.json "jest" object; JS config is never executed).
File-level spec discovery is exact (`npx jest <path>`); describe/
it/test names are listed as CANDIDATES — jest `-t` filtering is a
regex over the full name path, so individual-test selection is
exposed only when native collection proves an unambiguous identity.
Multi-project repos preserve `projects[].name` on file items.
"""
import json
import re
from .base import (Item, Result, glob_match, iter_files,
                   read_text_bounded, rel_posix, setting)
from .cypress import _literal

KIND = "jest"
CFG_NAMES = ["jest.config.js", "jest.config.ts", "jest.config.mjs",
             "jest.config.cjs", "package.json"]
DEFAULT_MATCH = ["**/__tests__/**/*.[jt]s?(x)",
                 "**/*.@(spec|test).[jt]s?(x)"]
_TEST_RE = re.compile(
    r"^\s*(?:describe|it|test|it\.each|test\.each|"
    r"describe\.skip|it\.skip|test\.skip|xit|xtest|"
    r"it\.todo|test\.todo)\s*(?:\.\w+)?\s*\(\s*"
    r"[\"'`]([^\"'`]+)[\"'`]", re.M)


def _read_config(base, cfg_rel, warnings):
    """Return (dict, src) — only literal values."""
    cands = [base / cfg_rel] if cfg_rel else \
        [base / c for c in CFG_NAMES]
    for p in cands:
        if not p.is_file():
            continue
        text = read_text_bounded(p, warnings, p.name)
        if text is None:
            continue
        rel = str(p.relative_to(base))
        if p.name == "package.json":
            try:
                cfg = json.loads(text).get("jest") or {}
            except Exception as exc:
                warnings.append(f"package.json: {exc}")
                cfg = {}
            if cfg:
                return {k: v for k, v in cfg.items()
                        if isinstance(v, (str, list, bool))}, rel
            continue
        out = {}
        for k in ("roots", "testMatch", "testPathIgnorePatterns",
                  "testEnvironment", "coverageDirectory"):
            lit = _literal(text, k)
            if lit is not None:
                out[k] = lit[0] if len(lit) == 1 and k in (
                    "testEnvironment", "coverageDirectory") else lit
        proj = re.search(r"projects\s*:\s*\[(.*?)\]", text, re.S)
        if proj:
            names = re.findall(
                r"(?:displayName|name)\s*:\s*[\"']([^\"']+)[\"']",
                proj.group(1))
            if names:
                out["projects"] = names
        # dynamic keys → warn (non-literal right-hand side)
        for k in ("roots", "testMatch", "projects"):
            if re.search(k + r"\s*:\s*[A-Za-z_$]", text) and \
                    k not in out:
                warnings.append(
                    f"{rel}: {k} is dynamic — unresolved statically")
        if out:
            return out, rel
    return {}, ""


def parse(ctx) -> Result:
    res = Result(method="static")
    base = ctx.base
    cfg, cfg_src = _read_config(base, ctx.fp.config_file,
                                res.warnings)
    if cfg_src:
        res.effective["config_file"] = setting(cfg_src, "config")
    elif ctx.fp.config_file:
        res.warnings.append(
            f"configured config {ctx.fp.config_file!r} not found")

    roots = ctx.fp.test_roots() or cfg.get("roots") or ["."]
    res.effective["roots"] = setting(
        roots, "override" if ctx.fp.test_roots()
        else "config" if cfg.get("roots") else "default")
    match = ctx.fp.include() or cfg.get("testMatch") or DEFAULT_MATCH
    res.effective["testMatch"] = setting(
        match, "override" if ctx.fp.include()
        else "config" if cfg.get("testMatch") else "default")
    ignore = ctx.fp.exclude() or cfg.get("testPathIgnorePatterns",
                                         [])
    res.effective["ignore"] = setting(
        ignore, "override" if ctx.fp.exclude()
        else "config" if cfg.get("testPathIgnorePatterns")
        else "default")
    projects = cfg.get("projects") or \
        ctx.fp.settings().get("projects", [])
    res.effective["projects"] = setting(
        projects, "config" if cfg.get("projects")
        else "override" if projects else "default")
    res.effective["testEnvironment"] = setting(
        cfg.get("testEnvironment") or "node",
        "config" if cfg.get("testEnvironment") else "default")

    matched = False
    for root in roots:
        rd = base if root in (".", "") else base / root
        if not rd.is_dir():
            res.warnings.append(f"test root {root!r} not found")
            continue
        for p in iter_files(rd, base, res.warnings):
            if p.suffix.lstrip(".") not in ("js", "jsx", "ts", "tsx",
                                            "mjs", "cjs"):
                continue
            rel = rel_posix(p, base)
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
            text = read_text_bounded(p, res.warnings, rel)
            if text:
                for m in _TEST_RE.finditer(text):
                    res.items.append(Item(
                        kind="test", path=rel, name=m.group(1),
                        parent=p.stem, node_id="",
                        granularity="test", selectable=False,
                        warnings="candidate — jest -t is a name "
                                 "regex; exact selection requires "
                                 "native collection"))
            if _TEST_RE.search(text):
                res.needs_native = True
    if not matched:
        res.warnings.append(
            "no test files matched — check roots/testMatch")
    return res
