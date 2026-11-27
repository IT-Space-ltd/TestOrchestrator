"""Bruno adapter — collection discovery for `bru` CLI execution.

Bruno collections are directory trees rooted at a marker file —
``bruno.json`` or ``opencollection.yml`` — containing ``.bru`` or
YAML request files, folders (with optional ``folder.bru``/
``bruno.yml`` metadata), environments, and scripts.

Static inspection is bounded and never executes: ``.bru`` files
are parsed for meta/name/type/tags/script-block PRESENCE (scripts
are repository code — flagged, not run, and no requests are sent).

Selection semantics (v4 docs):
- ``bru run [paths...]`` accepts multiple files/folders IN ORDER
  from the collection root — path-based identities, not names.
- Recursive folder execution is EXPLICIT (``-r``); it is never
  implied by selecting a folder.
- Duplicate request names across folders are unambiguous because
  the selector is the path.
- Assertions/tests inside a request are outcomes, not executable
  items.

Settings keys (fp.settings_json): collection_roots[] (roots
containing bruno.json/opencollection.yml; default: scan),
environment (--env name), environment_file (--env-file),
global_environment (--global-env), workspace_path, data_file,
iterations, delay_ms, include_tags, exclude_tags, tests_only,
bail, insecure, developer_mode (requires explicit approval —
developer mode widens script capabilities; safe sandbox is the
default), module_cache (never enabled by default).
"""
import json
import re
from .base import (Item, Result, glob_match, iter_files,
                   read_text_bounded, rel_posix, setting)

KIND = "bruno"
_ROOT_MARKERS = ("bruno.json", "opencollection.yml")
_REQ_EXT = (".bru",)
_YAML_REQ_KEYS = ("type:", "request:", "name:")   # opencollection
_META_NAME = re.compile(r'^\s*name:\s*(.+?)\s*$', re.M)
_META_TYPE = re.compile(r'^\s*type:\s*(.+?)\s*$', re.M)
_TAGS_RE = re.compile(r'^\s*tags?\s*:\s*\[?([^\]\n]*)', re.M)
_SCRIPT_RE = re.compile(
    r'^\s*(script(?::[\w-]+)?|tests|assert|vars(?::[\w-]+)?)\s*{',
    re.M)


def _collection_roots(base, configured, warnings):
    """Every directory carrying a Bruno root marker is a collection
    — arbitrarily nested, multiple per repo."""
    found = []
    if configured:
        for rel in configured:
            rd = base / rel
            if not rd.is_dir():
                warnings.append(f"collection root {rel!r} not found")
                continue
            if not any((rd / m).is_file() for m in _ROOT_MARKERS):
                warnings.append(
                    f"{rel}: no bruno.json / opencollection.yml — "
                    "not a Bruno collection root")
                continue
            found.append((rel, rd))
        return found
    # scan: walk, prune node_modules/.git
    for rd in sorted(base.rglob("*")):
        if not rd.is_dir():
            continue
        parts = rd.relative_to(base).parts
        if any(s in ("node_modules", ".git", "__pycache__")
               for s in parts):
            continue
        if any((rd / m).is_file() for m in _ROOT_MARKERS):
            found.append((rel_posix(rd, base), rd))
    return found


def _bru_request_meta(text):
    """Name/type/tags/script-presence from a .bru file — the meta
    block is what bru displays; blocks like script:* / tests /
    assert mean repository code runs at execution."""
    name = _META_NAME.search(text)
    rtype = _META_TYPE.search(text)
    tags = _TAGS_RE.search(text)
    script = bool(_SCRIPT_RE.search(text))
    return (name.group(1) if name else "",
            rtype.group(1) if rtype else "",
            [t.strip() for t in tags.group(1).split(",")
             if t.strip()] if tags else [],
            script)


def _yaml_request(text):
    """An opencollection YAML request — NOT every YAML file: must
    name a request type/name shape."""
    head = text[:2000]
    if not any(k in head for k in _YAML_REQ_KEYS):
        return None
    name = _META_NAME.search(text)
    rtype = _META_TYPE.search(text)
    return (name.group(1) if name else "",
            rtype.group(1) if rtype else "")


def parse(ctx) -> Result:
    res = Result(method="static")
    base = ctx.base
    st = ctx.fp.settings()
    for k in ("environment", "environment_file",
              "global_environment", "workspace_path", "data_file"):
        v = st.get(k) or ""
        res.effective[k] = setting(v, "override" if v else "default")
    for k in ("include_tags", "exclude_tags", "tests_only",
              "bail", "iterations", "delay_ms", "developer_mode"):
        v = st.get(k) or ""
        res.effective[k] = setting(v or "—",
                                   "override" if v else "default")

    configured = ctx.fp.test_roots()
    res.effective["collection_roots"] = setting(
        configured or ["<scan>"], "override" if configured
        else "default")
    exc = ctx.fp.exclude()
    roots = _collection_roots(base, configured, res.warnings)
    if not roots:
        res.warnings.append(
            "no Bruno collection roots (bruno.json / "
            "opencollection.yml) found under the checkout")
        return res
    for root_rel, rd in roots:
        marker = next(m for m in _ROOT_MARKERS if (rd / m).is_file())
        colname = root_rel or "."
        res.items.append(Item(
            kind="collection", path=root_rel or ".", name=colname,
            parent="", node_id=root_rel or ".",
            granularity="collection", selectable=True,
            tags=f"marker:{marker}"))
        env_dir = rd / "environments"
        env_names = []
        if env_dir.is_dir():
            for ef in sorted(env_dir.iterdir()):
                if ef.suffix.lower() in (".bru", ".yml", ".yaml",
                                         ".json"):
                    env_names.append(ef.stem)
                    res.items.append(Item(
                        kind="asset",
                        path=rel_posix(ef, base), name=ef.stem,
                        parent=colname, node_id="",
                        granularity="file", selectable=False,
                        tags="environment",
                        warnings="environment file — variable "
                                 "values are never surfaced"))
        for p in iter_files(rd, base, res.warnings):
            rel = rel_posix(p, base)
            if exc and glob_match(rel, exc):
                continue
            in_col = rel_posix(p, rd)
            if p.name in _ROOT_MARKERS:
                continue
            if p.suffix == ".bru":
                text = read_text_bounded(p, res.warnings, rel)
                if text is None:
                    continue
                name, rtype, tags, has_script = _bru_request_meta(
                    text)
                if rtype not in ("http", "graphql", "request"):
                    # folder.bru / meta blocks / non-request .bru
                    res.items.append(Item(
                        kind="asset", path=rel,
                        name=name or p.name,
                        parent=colname, node_id="",
                        granularity="file", selectable=False,
                        tags=f"bru-meta:{rtype or '?'}",
                        warnings="support/metadata file"))
                    continue
                res.items.append(Item(
                    kind="test", path=rel, name=name or p.stem,
                    parent=str(p.parent.relative_to(rd)),
                    node_id=in_col, granularity="request",
                    selectable=True,
                    tags=("in:" + colname +
                          (";tags:" + ",".join(tags) if tags else "") +
                          (";script" if has_script else "")),
                    warnings=("contains script/tests blocks — "
                              "executes only on the isolated target"
                              if has_script else "")))
            elif p.suffix.lower() in (".yml", ".yaml"):
                if p.name.startswith("opencollection"):
                    continue
                text = read_text_bounded(p, res.warnings, rel)
                if text is None:
                    continue
                y = _yaml_request(text)
                if y:
                    res.items.append(Item(
                        kind="test", path=rel, name=y[0] or p.stem,
                        parent=str(p.parent.relative_to(rd)),
                        node_id=in_col, granularity="request",
                        selectable=True, tags=f"in:{colname};yaml"))
            elif p.suffix.lower() in (".csv", ".json") and (
                    "iteration" in p.name.lower() or
                    p.name.lower().endswith(("-data.csv",
                                             "-data.json"))):
                res.items.append(Item(
                    kind="asset", path=rel, name=p.name,
                    parent=colname, node_id="",
                    granularity="file", selectable=False,
                    tags="dataset"))
        # folders: directories carrying request files — recursion is
        # explicit so folders are selectable units w/ folder node
        for d in sorted(rd.rglob("*")):
            if not d.is_dir() or d.name in ("environments",
                                            "node_modules"):
                continue
            drel = rel_posix(d, rd)
            if exc and glob_match(rel_posix(d, base), exc):
                continue
            has_req = any(
                c.is_file() and c.suffix == ".bru"
                for c in d.iterdir())
            if has_req:
                res.items.append(Item(
                    kind="folder", path=rel_posix(d, base),
                    name=d.name, parent=colname, node_id=drel,
                    granularity="folder", selectable=True,
                    tags=f"in:{colname}",
                    warnings="folder execution requires the "
                             "explicit recursion option"))
    return res
