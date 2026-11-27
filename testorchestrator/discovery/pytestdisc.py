"""pytest discovery adapter — static stdlib `ast` parse only.

What static inspection establishes: test files per configured
python_files patterns; test classes/functions; parametrize markers;
@pytest.mark.* markers. Exact `::nodeid` is emitted only for
unparametrized tests — parametrized expansion requires native
`pytest --collect-only` (arbitrary ids= make static resolution
unreliable) and is marked a non-selectable candidate.
"""
import ast
from .base import (Item, Result, glob_match, iter_files, nodeid_for,
                   read_text_bounded, rel_posix, setting)

KIND = "pytest"
DEFAULTS = {"python_files": ["test_*.py", "*_test.py"],
            "python_classes": ["Test*"],
            "python_functions": ["test*"],
            "testpaths": ["tests"]}


def _ini_config(base, rel_cfg, warnings):
    """Read pytest config literal settings — pytest.ini / setup.cfg /
    tox.ini / pyproject.toml. Returns (dict, source) — only literal
    keys; everything else stays default with source recorded."""
    import configparser
    import tomllib
    found = {}
    cand = []
    if rel_cfg:
        cand.append(base / rel_cfg)
    else:
        cand += [base / "pytest.ini", base / "pyproject.toml",
                 base / "setup.cfg", base / "tox.ini"]
    for p in cand:
        if not p.is_file():
            continue
        text = read_text_bounded(p, warnings, p.name)
        if text is None:
            continue
        try:
            if p.suffix == ".toml":
                data = tomllib.loads(text).get("tool", {}).get(
                    "pytest", {}).get("ini_options", {})
                for k in ("testpaths", "python_files",
                          "python_classes", "python_functions",
                          "addopts"):
                    if k in data:
                        v = data[k]
                        found[k] = v if isinstance(v, list) else \
                            str(v).split()
            else:
                cp = configparser.ConfigParser()
                cp.read_string(text)
                sect = "pytest" if p.name == "pytest.ini" else \
                    "tool:pytest"
                if cp.has_section(sect):
                    for k in ("testpaths", "python_files",
                              "python_classes", "python_functions",
                              "addopts"):
                        if cp.has_option(sect, k):
                            found[k] = cp.get(sect, k).split()
        except Exception as exc:
            warnings.append(f"{p.name}: config parse error ({exc})")
        if found:
            return found, str(p.relative_to(base))
    return found, ""


def _is_parametrized(fn) -> bool:
    for d in fn.decorator_list:
        s = ast.unparse(d) if hasattr(ast, "unparse") else ""
        if "parametrize" in s:
            return True
    return False


def _marks(fn) -> list:
    out = []
    for d in fn.decorator_list:
        try:
            s = ast.unparse(d)
        except Exception:
            continue
        if s.startswith("pytest.mark."):
            out.append(s[len("pytest.mark."):].split("(")[0])
        elif s.startswith("mark."):
            out.append(s[5:].split("(")[0])
    return out


def _walk_node(node, rel, prefix, res, fn_match):
    for ch in getattr(node, "body", []):
        if isinstance(ch, ast.ClassDef):
            if glob_match(ch.name, fn_match["python_classes"]):
                _walk_node(ch, rel, prefix + [ch.name], res, fn_match)
        elif isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not glob_match(ch.name, fn_match["python_functions"]):
                continue
            marks = _marks(ch)
            nid = nodeid_for(rel, prefix + [ch.name])
            if _is_parametrized(ch):
                res.items.append(Item(
                    kind="test", path=rel, name=ch.name,
                    parent="/".join(prefix) or "", node_id=nid,
                    granularity="test", selectable=False,
                    tags=",".join(marks),
                    warnings="parametrized — native collection "
                             "required to resolve case IDs"))
                res.needs_native = True
            else:
                res.items.append(Item(
                    kind="test", path=rel, name=ch.name,
                    parent="/".join(prefix) or "", node_id=nid,
                    granularity="test", selectable=True,
                    tags=",".join(marks)))


def parse(ctx) -> Result:
    res = Result(method="static")
    base = ctx.base
    cfg, cfg_src = _ini_config(base, ctx.fp.config_file, res.warnings)
    fn_match = {k: ctx.fp.settings().get(k) or cfg.get(k)
                or DEFAULTS[k]
                for k in ("python_files", "python_classes",
                          "python_functions")}
    for k, v in fn_match.items():
        src = ("override" if k in ctx.fp.settings()
               else "config" if k in cfg else "default")
        res.effective[k] = setting(v, src)
    if cfg_src:
        res.effective["config_file"] = setting(cfg_src, "config")
    elif ctx.fp.config_file:
        res.warnings.append(
            f"configured config file {ctx.fp.config_file!r} not found")
    roots = ctx.fp.test_roots() or cfg.get("testpaths") or \
        DEFAULTS["testpaths"]
    roots_src = ("override" if ctx.fp.test_roots()
                 else "config" if "testpaths" in cfg else "default")
    res.effective["test_roots"] = setting(roots, roots_src)
    inc = ctx.fp.include() or fn_match["python_files"]
    exc = ctx.fp.exclude()
    res.effective["include"] = setting(
        inc, "override" if ctx.fp.include() else "config")
    res.effective["exclude"] = setting(
        exc, "override" if ctx.fp.exclude() else "default")

    missing = 0
    for root in roots:
        rdir = (base / root)
        if not rdir.is_dir():
            missing += 1
            res.warnings.append(f"test root {root!r} not found")
            continue
        for p in iter_files(rdir, base, res.warnings):
            rel = rel_posix(p, base)
            if exc and glob_match(rel, exc):
                continue
            if p.suffix != ".py" or not glob_match(p.name, inc):
                continue
            text = read_text_bounded(p, res.warnings, rel)
            if text is None:
                continue
            try:
                tree = ast.parse(text, filename=rel)
            except SyntaxError as exc:
                res.warnings.append(f"{rel}: syntax error ({exc})")
                continue
            tests = [n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef,
                                       ast.AsyncFunctionDef))
                     and glob_match(n.name,
                                    fn_match["python_functions"])]
            if not tests:
                continue          # support file — not a test item
            res.items.append(Item(
                kind="suite", path=rel, name=p.stem,
                parent=str(p.parent.relative_to(base)),
                node_id=rel, granularity="file", selectable=True,
                tags=f"{len(tests)} tests"))
            _walk_node(tree, rel, [], res, fn_match)
            if len(res.items) >= 10000:
                res.warnings.append("item cap reached — partial")
                break
    if missing == len(roots):
        res.warnings.append("no test roots found — nothing discovered")
    return res
