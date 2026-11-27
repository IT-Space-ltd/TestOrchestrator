"""Retention (M9 §storage-7): separate artifact-file and
execution-metadata policies, project-over-global precedence,
preview-before-sweep, terminal-state + in-flight + unverified
safeguards, expired presentation."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from tests.conftest import login
from testorchestrator import retention, settings
from testorchestrator.extensions import db
from testorchestrator.execution import (
    Artifact, ArtifactStore, Execution, ExecutionState, Outcome,
    Project)


def _app(tmp_path):
    from tests.conftest import make_app, seed_users
    roots = tmp_path / "approved"
    app = make_app(tmp_path, "ret.db", TO_ARTIFACT_ROOTS=[str(roots)])
    with app.app_context():
        db.create_all()
    seed_users(app)
    return app, roots


def _finished_exec(project, report_dir, days_old=10, artifacts=("a.txt",)):
    rd = report_dir
    rd.mkdir(parents=True, exist_ok=True)
    for rel in artifacts:
        (rd / rel).write_text(f"data-{rel}")
    ex = Execution(project_id=project.id, source_sha="s",
                   report_dir=str(rd), snapshot_json="{}",
                   state=ExecutionState.COMPLETED,
                   outcome=Outcome.PASSED,
                   finished_at=datetime.now(timezone.utc)
                   - timedelta(days=days_old))
    db.session.add(ex)
    db.session.flush()
    for rel in artifacts:
        f = rd / rel
        from testorchestrator.results import sha256_file
        db.session.add(Artifact(
            execution_id=ex.id, kind="log", rel_path=rel,
            sha256=sha256_file(f), size=f.stat().st_size,
            mime="text/plain", mapped=True))
    db.session.commit()
    return ex, rd


def test_precedence_project_over_global(tmp_path):
    app, _ = _app(tmp_path)
    with app.app_context():
        p = Project(name="P", description="d")
        db.session.add(p)
        db.session.commit()
        settings.set("retention_artifact_days", 30)
        assert retention.effective_policy(p)["artifact_days"] == 30
        p.retention_json = json.dumps({"artifact_days": 7})
        assert retention.effective_policy(p)["artifact_days"] == 7
        p.retention_json = json.dumps({"artifact_days": 0})
        assert retention.effective_policy(p)["artifact_days"] == 0


def test_artifact_expiry_stored_only(tmp_path):
    """stored artifacts -> expired (durable object + staged file
    deleted); staged-only files (unverified, only copy) untouched;
    uploading untouched."""
    app, roots = _app(tmp_path)
    with app.app_context():
        p = Project(name="P", description="d")
        db.session.add(p)
        db.session.commit()
        p.retention_json = json.dumps({"artifact_days": 5})
        store = ArtifactStore(
            project_id=p.id, name="S", kind="local",
            config_json=json.dumps({"root": str(roots)}))
        db.session.add(store)
        db.session.flush()
        ex, rd = _finished_exec(p, tmp_path / "r1",
                                artifacts=("s.txt", "st.txt"))
        a_stored, a_staged = ex.artifacts[0], ex.artifacts[1]
        # simulate a stored artifact through the real put path
        from testorchestrator.storage import backend_for
        backend = backend_for(store)
        ref = backend.put(rd / "s.txt", f"{p.id}/{ex.id}/1/s.txt")
        a_stored.store_id = store.id
        a_stored.storage_ref = ref
        a_stored.storage_state = "stored"
        a_staged.storage_state = "staged"      # only copy, unverified
        db.session.commit()
        out = retention.sweep(project_id=p.id, actor="tester")
        assert out["artifacts_expired"] == 1
        assert out["artifact_errors"] == 0
        db.session.refresh(a_stored)
        assert a_stored.storage_state == "expired"
        assert not (rd / "s.txt").exists()
        assert not backend.path(ref).exists()          # durable copy gone
        db.session.refresh(a_staged)
        assert a_staged.storage_state == "staged"      # untouched
        assert (rd / "st.txt").exists()


def test_active_and_inflight_untouched(tmp_path):
    app, roots = _app(tmp_path)
    with app.app_context():
        p = Project(name="P", description="d")
        db.session.add(p)
        db.session.commit()
        p.retention_json = json.dumps({"artifact_days": 1})
        # running execution — no finished_at anyway
        rd = tmp_path / "run"
        rd.mkdir()
        (rd / "f.txt").write_text("x")
        ex = Execution(project_id=p.id, source_sha="s",
                       report_dir=str(rd), snapshot_json="{}",
                       state=ExecutionState.RUNNING)
        db.session.add(ex)
        db.session.commit()
        out = retention.sweep(project_id=p.id)
        assert out["artifacts_expired"] == 0
        assert (rd / "f.txt").exists()
        assert db.session.get(Execution, ex.id) is not None


def test_metadata_expiry_removes_execution(tmp_path):
    app, roots = _app(tmp_path)
    with app.app_context():
        p = Project(name="P", description="d")
        db.session.add(p)
        db.session.commit()
        p.retention_json = json.dumps({"metadata_days": 3})
        ex, rd = _finished_exec(p, tmp_path / "r2", days_old=10)
        eid = ex.id
        # newer execution below cutoff stays
        ex2, _ = _finished_exec(p, tmp_path / "r3", days_old=1)
        out = retention.sweep(project_id=p.id)
        assert out["executions_removed"] == 1
        assert db.session.get(Execution, eid) is None
        assert db.session.get(Execution, ex2.id) is not None


def test_preview_counts_no_mutation(tmp_path):
    app, roots = _app(tmp_path)
    with app.app_context():
        p = Project(name="P", description="d")
        db.session.add(p)
        db.session.commit()
        p.retention_json = json.dumps({"artifact_days": 1,
                                       "metadata_days": 1})
        ex, rd = _finished_exec(p, tmp_path / "r4", days_old=10)
        store = ArtifactStore(
            project_id=p.id, name="S", kind="local",
            config_json=json.dumps({"root": str(roots)}))
        db.session.add(store)
        db.session.flush()
        from testorchestrator.storage import backend_for
        ref = backend_for(store).put(rd / "a.txt",
                                     f"{p.id}/{ex.id}/1/a.txt")
        a = ex.artifacts[0]
        a.store_id = store.id
        a.storage_ref = ref
        a.storage_state = "stored"
        db.session.commit()
        out = retention.preview(project_id=p.id)
        assert out["artifacts"]["files"] == 1
        assert out["metadata"]["executions"] == 1
        assert a.storage_state == "stored"      # nothing deleted
        assert backend_for(store).path(ref).exists()


def test_run_requires_preview_first(app, client, tmp_path):
    """The destructive run is refused without a fresh preview."""
    login(client, "admin")
    with app.app_context():
        p = Project(name="P", description="d")
        db.session.add(p); db.session.commit()
        pid = p.id
    r = client.post(f"/projects/{pid}/retention/run",
                    follow_redirects=True)
    assert b"Run the preview first" in r.data


def test_policy_route_and_expired_badge(app, client, tmp_path):
    login(client, "admin")
    with app.app_context():
        p = Project(name="P", description="d")
        db.session.add(p)
        db.session.flush()
        ex = Execution(project_id=p.id, source_sha="s",
                       report_dir=str(tmp_path / "r5"),
                       snapshot_json="{}",
                       state=ExecutionState.COMPLETED,
                       outcome=Outcome.PASSED,
                       finished_at=datetime.now(timezone.utc))
        db.session.add(ex)
        db.session.flush()
        a = Artifact(execution_id=ex.id, kind="log", rel_path="x.txt",
                     sha256="0" * 64, size=3, mime="text/plain",
                     storage_state="expired")
        db.session.add(a)
        db.session.commit()
        pid, eid = p.id, ex.id
    r = client.post(f"/projects/{pid}/retention",
                    data={"artifact_days": "30", "metadata_days": "180"},
                    follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        assert json.loads(db.session.get(Project, pid).retention_json) \
            == {"artifact_days": 30, "metadata_days": 180}
    # expired artifact shown as policy expiry, not an unexplained
    # missing file
    body = client.get(f"/executions/{eid}").get_data(as_text=True)
    assert "expired" in body
    assert "retention policy" in body
    assert "expired under the retention policy" in body or \
        "removed under the retention policy" in body


def test_parse_days():
    assert retention.parse_days("") is None
    assert retention.parse_days("inherit") is None
    assert retention.parse_days("30") == 30
    assert retention.parse_days("0") == 0
    with pytest.raises(ValueError):
        retention.parse_days("-5")
    with pytest.raises(ValueError):
        retention.parse_days("abc")
