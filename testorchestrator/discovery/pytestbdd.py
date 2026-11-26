"""pytest-bdd adapter — links feature scenarios to executable
pytest test functions via `@scenario(...)` / `scenarios(...)`
AST calls. Two relationships kept distinct (review §3):
  binding   scenario → pytest test function (what can execute)
  matching  scenario step → step-definition (informational only)
A scenario is selectable only when an exact bound test exists —
parametrized/custom-id bindings are candidates needing native
collection."""
import ast
from .base import (Item, Result, glob_match, iter_files, nodeid_for,
                   read_text_bounded, rel_posix, setting)
from . import gherkin

KIND = "pytest-bdd"


def _lit(node):
    """Literal str arg → value, else None (non-literal = dynamic)."""
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _resolve(feat_arg: str, test_rel: str) -> str:
    """Decorator paths are relative to the TEST FILE's directory —
    normalize to repo-relative."""
    import posixpath
    base_dir = posixpath.dirname(test_rel)
    return posixpath.normpath(posixpath.join(base_dir, feat_arg))


def _collect_bindings(py_files, base, res):
    """Return {(feature_rel, scenario_name): nodeid} plus counts of
    wildcard `scenarios(...)` binds (those mark the feature file's
    scenarios bound by name — still exact)."""
    bound = {}
    wildcard = {}
    dynamic_calls = 0
    for rel in py_files:
        p = base / rel
        text = read_text_bounded(p, res.warnings, rel)
        if text is None:
            continue
        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError as exc:
            res.warnings.append(f"{rel}: syntax error ({exc})")
            continue
        def _handle_call(d, fn_name):
            nonlocal dynamic_calls
            if not isinstance(d, ast.Call):
                return
            name = ast.unparse(d.func) if hasattr(
                ast, "unparse") else ""
            if name.endswith("scenario") and \
                    not name.endswith("scenarios"):
                args = [_lit(a) for a in d.args]
                feat = next((a for a in args
                             if isinstance(a, str) and
                             a.endswith(".feature")), None)
                scen = next((a for a in args
                             if isinstance(a, str) and
                             not a.endswith(".feature")), None)
                if feat and scen:
                    bound[(_resolve(feat, rel), scen)] = \
                        nodeid_for(rel, [fn_name])
                else:
                    dynamic_calls += 1
            elif name.endswith("scenarios"):
                feat = _lit(d.args[0]) if d.args else None
                if isinstance(feat, str):
                    # may name a dir (all features under it) or
                    # a single .feature — resolved in parse()
                    wildcard.setdefault(
                        _resolve(feat, rel), []).append(
                        nodeid_for(rel, [fn_name]))
                else:
                    dynamic_calls += 1

        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef,
                               ast.AsyncFunctionDef)):
                for d in fn.decorator_list:
                    _handle_call(d, fn.name)
            # module-level `scenarios("dir")` is an Expr/Assign
            # call, not a decorator — same literal handling.
            elif isinstance(fn, (ast.Expr, ast.Assign)):
                val = fn.value
                if isinstance(val, ast.Call):
                    _handle_call(val, "")
    return bound, wildcard, dynamic_calls


def parse(ctx) -> Result:
    res = Result(method="static")
    base = ctx.base
    feat_roots = ctx.fp.feature_roots() or ["features"]
    test_roots = ctx.fp.test_roots() or ["tests"]
    res.effective["feature_roots"] = setting(
        feat_roots, "override" if ctx.fp.feature_roots() else
        "default")
    res.effective["test_roots"] = setting(
        test_roots, "override" if ctx.fp.test_roots() else "default")
    exc = ctx.fp.exclude()

    feats, py_files = [], []
    for root in feat_roots + test_roots:
        rd = base / root
        if not rd.is_dir():
            res.warnings.append(f"root {root!r} not found")
            continue
        for p in iter_files(rd, base, res.warnings):
            rel = rel_posix(p, base)
            if exc and glob_match(rel, exc):
                continue
            if p.suffix == ".feature" and root in feat_roots:
                feats.append((rel, p))
            elif p.suffix == ".py":
                py_files.append(rel)

    bound, wildcard, dyn = _collect_bindings(py_files, base, res)
    if dyn:
        res.warnings.append(
            f"{dyn} non-literal @scenario/scenarios call(s) — "
            "dynamic bindings unresolved statically")
        res.needs_native = True

    for rel, p in feats:
        text = read_text_bounded(p, res.warnings, rel)
        if text is None:
            continue
        feat = gherkin.parse_feature(text, rel)
        res.warnings += feat["warnings"]
        # Resolve per-scenario bindings first: the feature's suite
        # item is executable only through the exact node IDs of its
        # bound scenarios — pytest never collects a bare .feature
        # positional (ISS-026), so a feature with no exact binding
        # is marked not selectable with the reason.
        scen_items = []
        exact_nids = []
        for s in feat["scenarios"]:
            nid = bound.get((rel, s["name"]))
            warn = ""
            wild_hit = rel in wildcard or any(
                rel.startswith(w.rstrip("/") + "/")
                for w in wildcard if not w.endswith(".feature"))
            if nid is None and wild_hit:
                # scenarios() generates test_<slug> node IDs — the
                # exact selector is not statically derivable
                warn = ("bound via scenarios() — generated node IDs "
                        "require native collection to select")
                res.needs_native = True
            elif nid is None:
                warn = ("no @scenario/scenarios binding found — "
                        "native collection required")
                res.needs_native = True
            if nid:
                exact_nids.append(nid)
            scen_items.append(Item(
                kind="scenario", path=rel, name=s["name"],
                parent=feat["title"] or p.stem,
                node_id=nid or "",
                granularity="scenario", selectable=bool(nid),
                tags=",".join(s["tags"]), warnings=warn))
        suite_warn = ""
        suite_selectable = True
        if not exact_nids:
            suite_selectable = False
            if feat["scenarios"]:
                suite_warn = (
                    "no exact @scenario binding for any scenario — "
                    "feature-level selection cannot resolve node IDs; "
                    "bind scenarios with @scenario(feature, name) or "
                    "use native collection")
            else:
                suite_warn = "feature has no scenarios"
        res.items.append(Item(
            kind="suite", path=rel, name=feat["title"] or p.stem,
            parent=str(p.parent.relative_to(base)),
            node_id=rel, granularity="file",
            selectable=suite_selectable,
            tags=",".join(feat["tags"]), warnings=suite_warn))
        res.items.extend(scen_items)
    if not feats:
        res.warnings.append("no .feature files under feature roots")
    return res
