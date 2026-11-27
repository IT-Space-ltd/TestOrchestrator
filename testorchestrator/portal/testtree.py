"""Test-tab tree view: collection → suite → test cases, read-only.

Pure builder over the discovered inventory — no schema, no writes.
Granularity labels are per-framework (Cypress is file-level only);
stale badges are a render-time set-diff against the current inventory
(warn-only, never dropped); last results come from ONE rollup query
executed by the caller.
"""
import json

# granularity label per framework — Cypress is file-level only.
GRANULARITY = {
    "katalon": "case",
    "cypress": "file",
    "playwright": "test",
    "pytest": "test",
    "pytest-bdd": "scenario",
    "behave": "scenario",
    "robot": "test",
    "gtest": "test",
    "jest": "test",
    "postman": "request",
    "bruno": "request",
}


def granularity_label(framework: str) -> str:
    return GRANULARITY.get((framework or "").lower(), "file")


def build_tree(items, last_results):
    """items: DiscoveredItem rows for the project (current inventory).
    last_results: {source_item_id: {"outcome": str, "finished_at": str}}
    Returns {"collections": [...], "suites": [...], "stale": int}.
    Every node carries escaped-by-template fields only — no HTML here.
    """
    by_path = {}          # (binding_id, path) -> item  (suites/cases)
    suites, colls = [], []
    for it in items:
        by_path[(it.binding_id, it.path)] = it
        if it.kind == "suite":
            suites.append(it)
        elif it.kind == "collection":
            colls.append(it)

    def members_of(item):
        try:
            return json.loads(item.members_json or "[]")
        except (TypeError, ValueError):
            return []

    def last(item):
        return last_results.get(item.id)

    def case_children(suite):
        """Test cases under a suite: member refs that resolve in the
        current inventory, plus test-level items whose file path is
        the suite path (pytest/robot/etc. node-id items)."""
        out, stale = [], 0
        member_paths = set(members_of(suite))
        for ref in sorted(member_paths):
            node = by_path.get((suite.binding_id, ref))
            if node is not None:
                out.append(node)
            else:
                stale += 1
        if not member_paths:
            # framework discovery: test-level items sharing the file
            for it in items:
                if it.id == suite.id or it.kind in ("suite",
                                                    "collection"):
                    continue
                if it.binding_id != suite.binding_id:
                    continue
                if (it.node_id and (it.path == suite.path or
                                    it.parent == suite.path)):
                    out.append(it)
        return out, stale

    def suite_node(suite):
        cases, stale_cases = case_children(suite)
        fw = suite.framework or "katalon"
        return {
            "id": suite.id, "name": suite.name or suite.path,
            "path": suite.path, "framework": fw,
            "granularity": granularity_label(fw),
            "cases": [{"id": c.id, "name": c.name or c.path,
                       "path": c.path,
                       "last": last(c)} for c in cases],
            "case_count": len(cases),
            "stale_count": stale_cases,
            "selectable": bool(suite.selectable),
            "last": last(suite),
            "repo": True,
        }

    suite_ids_in_colls = set()
    coll_nodes = []
    total_stale = 0
    for coll in sorted(colls, key=lambda c: c.path):
        member_suites, stale_members = [], 0
        for ref in members_of(coll):
            node = by_path.get((coll.binding_id, ref))
            if node is not None and node.kind == "suite":
                member_suites.append(node)
                suite_ids_in_colls.add(node.id)
            else:
                stale_members += 1
        total_stale += stale_members
        runmode = next((t[8:] for t in (coll.tags or "").split(";")
                        if t.startswith("runmode:")), "")
        snodes = [suite_node(s) for s in member_suites]
        total_stale += sum(s["stale_count"] for s in snodes)
        coll_nodes.append({
            "id": coll.id, "name": coll.name or coll.path,
            "path": coll.path, "framework": coll.framework or "katalon",
            "runmode": runmode or "sequential",
            "suites": snodes,
            "suite_count": len(snodes),
            "case_count": sum(s["case_count"] for s in snodes),
            "stale_count": stale_members + sum(
                s["stale_count"] for s in snodes),
            "last": last(coll),
            "repo": True,
        })

    loose = [suite_node(s) for s in sorted(suites, key=lambda x: x.path)
             if s.id not in suite_ids_in_colls]
    total_stale += sum(s["stale_count"] for s in loose)
    return {"collections": coll_nodes, "suites": loose,
            "stale": total_stale}


def rollup_last_results(db, Execution, project_id):
    """ONE rollup query — latest finished execution per source item.
    Returns {source_item_id: {"outcome", "finished_at", "state"}}."""
    rows = (db.session.query(
        Execution.source_item_id, Execution.outcome, Execution.state,
        Execution.finished_at)
        .filter(Execution.project_id == project_id,
                Execution.source_item_id.isnot(None),
                Execution.finished_at.isnot(None))
        .order_by(Execution.finished_at.desc()).all())
    out = {}
    for item_id, outcome, state, fin in rows:
        if item_id in out:          # rows are newest-first
            continue
        out[item_id] = {
            "outcome": getattr(outcome, "value", str(outcome or "")),
            "state": getattr(state, "value", str(state or "")),
            "finished_at": fin.isoformat() if fin else "",
        }
    return out
