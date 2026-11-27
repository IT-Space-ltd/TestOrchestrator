"""Cypress adapter — file-level spec discovery only (reliable
granularity; per-test `--spec`+`-g` filtering is NOT exact, so no
test-level selection is exposed). Config is literal-extracted —
JS config is never executed: `specPattern`, `excludeSpecPattern`,
`testingType`/`e2e`/`component` read via bounded regex; imported
or computed config → 'unresolved statically' warning and explicit
defaults (with source='default', never silent substitution)."""
import re
from .base import (Item, Result, glob_match, iter_files,
                   read_text_bounded, rel_posix, setting)

KIND = "cypress"
DEFAULT_SPEC = ["cypress/e2e/**/*.cy.{js,jsx,ts,tsx}",
                "**/*.cy.{js,jsx,ts,tsx}"]
CFG_NAMES = ["cypress.config.js", "cypress.config.ts",
             "cypress.config.mjs", "cypress.config.cjs",
             "cypress.json"]


def _literal(text, key):
    """Extract a literal string/array value for `key` from config
    text — returns None for anything non-literal (variables,
    imports, expressions)."""
    m = re.search(key + r"\s*:\s*(\[[^\]]*\]|\"[^\"]*\"|'[^']*')",
                  text)
    if not m:
        return None
    v = m.group(1).strip()
    if v.startswith("["):
        inner = [x.strip().strip("\"'")
                 for x in v[1:-1].split(",") if x.strip()]
        return inner
    return [v.strip("\"'")]


def parse(ctx) -> Result:
    res = Result(method="static")
    base = ctx.base
    cfg_rel = ctx.fp.config_file
    cfg_text = None
    cfg_src = ""
    cands = [base / cfg_rel] if cfg_rel else \
        [base / c for c in CFG_NAMES]
    for p in cands:
        if p.is_file():
            cfg_text = read_text_bounded(p, res.warnings, p.name)
            cfg_src = str(p.relative_to(base))
            break
    spec = ctx.fp.include()
    excl = ctx.fp.exclude()
    spec_src = "override" if spec else "default"
    excl_src = "override" if excl else "default"
    ttype = ""
    if cfg_text is not None:
        res.effective["config_file"] = setting(cfg_src, "config")
        lit = _literal(cfg_text, "specPattern")
        if lit and not spec:
            spec, spec_src = lit, "config"
        e = _literal(cfg_text, "excludeSpecPattern")
        if e and not excl:
            excl, excl_src = e, "config"
        for m in re.finditer(r"(e2e|component)\s*:", cfg_text):
            ttype = m.group(1)
            break
        if re.search(r"specPattern\s*:\s*[A-Za-z_$]", cfg_text) \
                and not spec:
            res.warnings.append(
                f"{cfg_src}: specPattern is dynamic (imported or "
                "computed) — unresolved statically; no default "
                "substituted")
    elif cfg_rel:
        res.warnings.append(
            f"configured config {cfg_rel!r} not found — using "
            "explicit include/test_roots only")
    if not spec:
        spec = ctx.fp.test_roots() or DEFAULT_SPEC
        spec_src = "override" if ctx.fp.test_roots() else "default"
    res.effective["specPattern"] = setting(spec, spec_src)
    res.effective["excludeSpecPattern"] = setting(excl, excl_src)
    res.effective["testingType"] = setting(ttype or "e2e",
                                           "config" if ttype else
                                           "default")

    inc_fns = [p for p in spec if "*" in p or p.endswith(
        (".js", ".ts", ".jsx", ".tsx"))]
    matched = False
    for root in ctx.fp.test_roots() or ["."]:
        rd = base if root in (".", "") else base / root
        if not rd.is_dir():
            res.warnings.append(f"test root {root!r} not found")
            continue
        for p in iter_files(rd, base, res.warnings):
            rel = rel_posix(p, base)
            if not glob_match(rel, inc_fns):
                continue
            if excl and glob_match(rel, excl):
                continue
            matched = True
            res.items.append(Item(
                kind="suite", path=rel, name=p.stem,
                parent=str(p.parent.relative_to(base)),
                node_id=rel, granularity="file", selectable=True,
                tags=ttype or "e2e"))
    if not matched:
        res.warnings.append(
            "no spec files matched specPattern — check config or "
            "include patterns")
    return res
