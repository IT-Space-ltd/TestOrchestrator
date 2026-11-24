"""Postman adapter — collection/environment/dataset discovery.

Static inspection is authoritative for collection STRUCTURE:
Postman collections are JSON documents, so parsing them executes
nothing (pre-request/test scripts are flagged, never run, and no
API requests are sent — §1: scripts are repository code and only
run on the approved isolated target).

Selection honesty (§2): a collection is file-level executable by
either engine. Newman selects folders by name via ``--folder`` —
a folder item is selectable only when its name is unique inside
its collection (duplicates get a warning and stay candidates).
Requests are never independently executable (no engine selector);
assertions inside scripts are execution outcomes, not tests.
postman-cli reports vary by collection format — capability is
probed, not promised.

Settings keys (fp.settings_json): engine ("newman"|"postman-cli",
default newman), environment_file, globals_file, data_file,
iterations, delay_ms, timeout_ms, insecure (TLS verification is
ON unless insecure=true is explicitly configured), capture_bodies
(redaction control — raw request/response bodies stay out of
artifacts unless opted in).
"""
import json
from .base import (Item, Result, glob_match, iter_files,
                   read_text_bounded, rel_posix, setting)

KIND = "postman"
ENGINES = ("newman", "postman-cli")
_SCHEMA_MARKERS = ("collection", "schema.getpostman.com",
                   "schema.postman.com")


def _collection_doc(text, rel, warnings):
    """Validate Postman collection JSON by content — filename and
    location carry no meaning (§1)."""
    try:
        doc = json.loads(text)
    except ValueError:
        return None                     # not JSON — not a collection
    info = doc.get("info")
    if not isinstance(info, dict) or "item" not in doc:
        return None
    schema = str(info.get("schema") or "")
    if not any(m in schema for m in _SCHEMA_MARKERS):
        warnings.append(
            f"{rel}: JSON with info/item but no recognized Postman "
            "collection schema — skipped")
        return None
    return doc


def _var_names(container, out):
    """Variable NAMES only — values can hold secrets (§1/§4)."""
    for v in container.get("variable") or []:
        if isinstance(v, dict) and v.get("key"):
            out.add(str(v["key"])[:64])
    auth = container.get("auth")
    if isinstance(auth, dict):
        for param in auth.get(auth.get("type", ""), []) or []:
            if isinstance(param, dict) and param.get("key"):
                out.add(str(param["key"])[:64])


_V3_MARKER = "definition.yaml"
_V3_RESERVED = {"resources", "environments", "scripts",
                "globals", "docs"}


def _v3_request_name(text):
    """A v3/opencollection YAML REQUEST file — not every YAML: the
    document must carry a request-ish identity."""
    head = text[:3000]
    if "definition.yaml" in head or \
            not any(k in head for k in
                    ("request:", "type: request", "method:",
                     "name:")):
        return None
    for line in head.splitlines():
        ls = line.strip()
        if ls.startswith("name:"):
            return ls.split(":", 1)[1].strip().strip("'\"") or None
    return ""


def _v3_scan(rd, base, rel_root, engine, res):
    """v3 native-git collection: definition.yaml marks the root;
    request YAML files are individually path-selectable for
    postman-cli (the documented v3 selector); folders hold their own
    definition.yaml. Newman CANNOT run v3 — compatibility gate."""
    col_path = rel_root
    cname = rd.name
    txt = read_text_bounded(rd / _V3_MARKER, res.warnings,
                            rel_posix(rd / _V3_MARKER, base)) or ""
    for line in txt.splitlines()[:80]:
        if line.strip().startswith("name:"):
            cname = line.split(":", 1)[1].strip().strip("'\"") \
                or cname
            break
    v3_cli = engine == "postman-cli"
    res.items.append(Item(
        kind="collection", path=rel_posix(rd, base), name=cname,
        parent="", node_id=rel_posix(rd, base) if v3_cli else "",
        granularity="file", selectable=v3_cli,
        tags="format:v3",
        warnings="" if v3_cli else
        "collection v3 (YAML) — Newman is unmaintained and cannot "
        "execute it; select the postman-cli engine"))
    for p in iter_files(rd, base, res.warnings):
        rel = rel_posix(p, base)
        parts = p.relative_to(rd).parts
        if any(part in _V3_RESERVED for part in parts[:-1]):
            continue
        if p.name == _V3_MARKER:
            folder_dir = rel_posix(p.parent, base)
            res.items.append(Item(
                kind="folder" if len(parts) > 1 else "asset",
                path=rel, name=p.parent.name,
                parent=cname,
                node_id=(folder_dir if (len(parts) > 1
                                        and v3_cli) else ""),
                granularity="folder" if len(parts) > 1 else "file",
                selectable=len(parts) > 1 and v3_cli,
                tags=f"in:{col_path}",
                warnings="" if v3_cli else
                "v3 folder — postman-cli only"))
            continue
        if p.suffix.lower() not in (".yaml", ".yml"):
            continue
        text = read_text_bounded(p, res.warnings, rel)
        if text is None:
            continue
        name = _v3_request_name(text)
        if name is None:
            continue
        res.items.append(Item(
            kind="test", path=rel, name=name or p.stem,
            parent=str(p.parent.relative_to(rd)),
            node_id=rel if v3_cli else "",
            granularity="request",
            selectable=v3_cli,
            tags=f"in:{col_path};format:v3",
            warnings="" if v3_cli else
            "v3 request — postman-cli required (newman cannot "
            "execute collection v3)"))


def _walk_items(items, prefix, out_items, req_names, var_names,
                has_scripts):
    """Recurse folder → request tree. Requests contribute names to
    the duplicate-name index; scripts are flagged, not read."""
    for it in items or []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "(unnamed)")
        if "item" in it:                     # folder
            fpath = f"{prefix}/{name}" if prefix else name
            out_items.append(("folder", name, fpath))
            _walk_items(it.get("item"), fpath, out_items, req_names,
                        var_names, has_scripts)
            continue
        if it.get("request") is not None:    # request
            fpath = f"{prefix}/{name}" if prefix else name
            out_items.append(("request", name, fpath))
            req_names.append(name)
        for ev in it.get("event") or []:
            if isinstance(ev, dict) and ev.get("listen") in (
                    "prerequest", "test") and \
                    (ev.get("script") or {}).get("exec"):
                has_scripts.append(ev.get("listen"))
        _var_names(it, var_names)


def parse(ctx) -> Result:
    res = Result(method="static")
    base = ctx.base
    st = ctx.fp.settings()
    engine = st.get("engine") or "newman"
    if engine not in ENGINES:
        res.warnings.append(
            f"unknown engine {engine!r} — expected one of "
            f"{', '.join(ENGINES)}; falling back to newman")
        engine = "newman"
    res.effective["engine"] = setting(
        engine, "override" if st.get("engine") else "default")

    roots = ctx.fp.test_roots() or ["."]
    pats = ctx.fp.include() or ["**/*.json"]
    exc = ctx.fp.exclude()
    res.effective["collection_roots"] = setting(
        roots, "override" if ctx.fp.test_roots() else "default")
    res.effective["collection_patterns"] = setting(
        pats, "override" if ctx.fp.include() else "default")
    for k in ("environment_file", "globals_file", "data_file"):
        v = st.get(k) or ""
        res.effective[k] = setting(v, "override" if v else "default")

    # Collection discovery: every JSON file under roots is a v2.1
    # candidate; every directory with definition.yaml is a v3
    # collection root. Only schema-validated docs become collections.
    seen_collections = 0
    seen_v3 = set()
    for root in roots:
        rd = base if root in (".", "") else base / root
        if not rd.is_dir():
            res.warnings.append(f"collection root {root!r} not found")
            continue
        # depth-first ordering: shallow roots scan before nested
        # definition.yaml dirs so folders never become roots
        for d in sorted(rd.rglob(_V3_MARKER),
                        key=lambda p: len(p.parts)):
            dd = d.parent
            if dd in seen_v3 or any(
                    anc in seen_v3 for anc in dd.parents):
                continue
            seen_v3.add(dd)
            seen_collections += 1
            _v3_scan(dd, base, rel_posix(dd, base), engine, res)
        if (rd / _V3_MARKER).is_file() and rd not in seen_v3:
            seen_v3.add(rd)
            seen_collections += 1
            _v3_scan(rd, base, root if root not in (".", "")
                     else ".", engine, res)
        for p in iter_files(rd, base, res.warnings):
            if p.suffix.lower() != ".json":
                continue
            rel = rel_posix(p, base)
            if exc and glob_match(rel, exc):
                continue
            if not glob_match(rel, pats):
                continue
            text = read_text_bounded(p, res.warnings, rel)
            if text is None:
                continue
            doc = _collection_doc(text, rel, res.warnings)
            if doc is None:
                continue
            seen_collections += 1
            cname = str((doc.get("info") or {}).get("name")
                        or p.stem)
            res.items.append(Item(
                kind="collection", path=rel, name=cname,
                parent=str(p.parent.relative_to(base)),
                node_id=rel, granularity="file", selectable=True,
                tags=f"format:v2.1;engine:{engine}"))
            out, req_names, var_names, scripts = [], [], set(), []
            _var_names(doc, var_names)
            _walk_items(doc.get("item"), "", out, req_names,
                        var_names, scripts)
            folder_counts = {}
            for kind, name, fpath in out:
                if kind == "folder":
                    folder_counts[fpath.split("/")[-1]] = \
                        folder_counts.get(
                            fpath.split("/")[-1], 0) + 1
            for kind, name, fpath in out:
                if kind == "folder":
                    leaf = fpath.split("/")[-1]
                    dup = folder_counts.get(leaf, 0) > 1
                    selectable = engine == "newman" and not dup
                    res.items.append(Item(
                        kind="folder", path=rel, name=fpath,
                        parent=cname,
                        node_id=fpath if selectable else "",
                        granularity="folder",
                        selectable=selectable,
                        tags=f"in:{rel}",
                        warnings=("" if selectable else
                                  ("duplicate folder name — "
                                   "--folder is name-based; select "
                                   "at collection level" if dup else
                                   f"folder selection not verified "
                                   f"for engine {engine!r}"))))
                else:  # request — display-only, never executable
                    res.items.append(Item(
                        kind="test", path=rel, name=name,
                        parent=fpath.rsplit("/", 1)[0],
                        node_id="", granularity="request",
                        selectable=False,
                        tags=f"in:{rel}",
                        warnings="request — executed via its "
                                 "collection/folder; assertions are "
                                 "report outcomes, not tests"))
            if scripts:
                res.warnings.append(
                    f"{rel}: contains {sorted(set(scripts))} scripts "
                    "— repository code, runs only on the isolated "
                    "target; requests may execute indirectly through "
                    "collection workflow logic")
            # variable names attach to the collection item (never
            # the values)
            col_item = res.items[-(len(out) + 1)]
            if var_names:
                col_item.tags = (col_item.tags +
                                 ";vars:" +
                                 ",".join(sorted(var_names)[:16]))

    # Environment / globals / dataset assets — discovered, displayed,
    # never selectable.
    for key, label in (("environment_file", "environment"),
                       ("globals_file", "globals"),
                       ("data_file", "dataset")):
        rel = st.get(key) or ""
        if not rel:
            continue
        p = base / rel
        ok = p.is_file()
        if ok and key != "data_file":
            text = read_text_bounded(p, res.warnings, rel)
            if text:
                try:
                    doc = json.loads(text)
                    names = [str(v.get("key")) for v in
                             doc.get("values") or []
                             if isinstance(v, dict) and v.get("key")]
                    res.items.append(Item(
                        kind="asset", path=rel, name=p.name,
                        node_id="", granularity="file",
                        selectable=False,
                        tags=f"{label};vars:{','.join(names[:16])}",
                        warnings=f"{label} file — {len(names)} "
                                 "variables (names only, values "
                                 "never surfaced)"))
                    continue
                except ValueError:
                    res.warnings.append(
                        f"{label} file {rel!r} is not valid JSON")
        res.items.append(Item(
            kind="asset", path=rel, name=rel.rsplit("/", 1)[-1],
            node_id="", granularity="file", selectable=False,
            tags=label,
            warnings=(f"{label} file" if ok else
                      f"{label} file {rel!r} NOT FOUND — runs "
                      "referencing it will fail")))
    if not seen_collections:
        res.warnings.append(
            "no valid Postman collections under the configured "
            "roots/patterns")
    return res
