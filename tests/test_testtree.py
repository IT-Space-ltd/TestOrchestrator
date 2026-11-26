"""Tree view (Test tab): builder correctness, stale warn-only badges,
one-rollup-query proof, granularity labels, escaping."""
import json

from testorchestrator.execution import (DiscoveredItem, Execution, GitBinding,
                                        Outcome, Project)
from testorchestrator.extensions import db
from testorchestrator.portal.testtree import (build_tree, granularity_label,
                                              rollup_last_results)


def _mk(app, fw="katalon"):
    """Project + binding + collection(smoke.tsc -> login.ts) + suite
    (login.ts -> case a.tc) + case. Returns ids."""
    with app.app_context():
        p = Project(name="T"); db.session.add(p); db.session.flush()
        b = GitBinding(project_id=p.id, name="b", url="/x",
                       worktree_path="/tmp/x")
        db.session.add(b); db.session.flush()
        case = DiscoveredItem(
            project_id=p.id, binding_id=b.id, sha="s", kind="case",
            path="Test Cases/a.tc", name="a", framework=fw)
        suite = DiscoveredItem(
            project_id=p.id, binding_id=b.id, sha="s", kind="suite",
            path="Test Suites/login.ts", name="login", framework=fw,
            members_json='["Test Cases/a.tc"]')
        coll = DiscoveredItem(
            project_id=p.id, binding_id=b.id, sha="s", kind="collection",
            path="Test Suites/smoke.tsc", name="smoke", framework=fw,
            members_json='["Test Suites/login.ts"]',
            tags="runmode:SEQUENTIAL")
        db.session.add_all([case, suite, coll])
        db.session.commit()
        return p.id, b.id, case.id, suite.id, coll.id


def test_tree_nests_collection_suite_case(app):
    pid, bid, caid, suid, coid = _mk(app)
    with app.app_context():
        items = DiscoveredItem.query.all()
        tree = build_tree(items, {})
        assert len(tree["collections"]) == 1
        coll = tree["collections"][0]
        assert coll["suite_count"] == 1
        assert coll["case_count"] == 1
        assert coll["runmode"] == "SEQUENTIAL"
        assert coll["repo"] is True
        suite = coll["suites"][0]
        assert suite["case_count"] == 1
        assert suite["cases"][0]["path"] == "Test Cases/a.tc"
        assert suite["stale_count"] == 0
        assert tree["suites"] == []      # login.ts is inside the collection


def test_stale_members_warn_only_never_dropped(app):
    pid, bid, caid, suid, coid = _mk(app)
    with app.app_context():
        # remove the case and the suite from inventory — collection and
        # suite keep their member refs (repo files unchanged conceptually,
        # inventory lost them). Entries must still render, with badges.
        DiscoveredItem.query.filter_by(kind="case").delete()
        db.session.commit()
        items = DiscoveredItem.query.all()
        tree = build_tree(items, {})
        coll = tree["collections"][0]
        assert coll["suite_count"] == 1       # suite still listed
        suite = coll["suites"][0]
        assert suite["stale_count"] == 1      # a.tc unresolvable -> warn
        assert suite["case_count"] == 0       # but no resolved children


def test_granularity_labels():
    assert granularity_label("cypress") == "file"
    assert granularity_label("pytest-bdd") == "scenario"
    assert granularity_label("jest") == "test"
    assert granularity_label("unknown-fw") == "file"


def test_rollup_is_single_query(app):
    pid, bid, caid, suid, coid = _mk(app)
    with app.app_context():
        from datetime import datetime, timezone
        for item_id, out in ((suid, Outcome.PASSED),
                             (coid, Outcome.FAILED)):
            db.session.add(Execution(
                project_id=pid, source_item_id=item_id, outcome=out,
                finished_at=datetime.now(timezone.utc)))
        db.session.commit()
        queries = []
        from sqlalchemy import event
        engine = db.session.get_bind()

        def count(*a, **k):
            queries.append(1)
        event.listen(engine, "before_cursor_execute", count)
        try:
            res = rollup_last_results(db, Execution, pid)
        finally:
            event.remove(engine, "before_cursor_execute", count)
        assert len(queries) == 1, f"expected ONE query, got {len(queries)}"
        assert res[suid]["outcome"] == "passed"
        assert res[coid]["outcome"] == "failed"


def test_tree_renders_escaped_and_badged(app, client, login_as):
    pid, bid, caid, suid, coid = _mk(app)
    with app.app_context():
        # hostile content — must render escaped
        it = DiscoveredItem.query.get(caid)
        it.name = '<script>alert("x")</script>'
        db.session.commit()
    login_as("admin")
    resp = client.get(f"/projects/{pid}?tab=test&subtab=tree")
    body = resp.data.decode()
    assert resp.status_code == 200
    assert '<script>alert("x")</script>' not in body
    assert "&lt;script&gt;" in body
    assert 'role="tree"' in body
    assert "aria-expanded" in body
    assert ">repo</span>" in body
    assert "test-tree.js" in body
