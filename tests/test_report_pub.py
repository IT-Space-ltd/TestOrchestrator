"""Report publication + synchronized deletion — local fixture repos."""

import json
from pathlib import Path

from testorchestrator import dispatch, gitsync
from testorchestrator.extensions import db
from testorchestrator.execution import (Execution, ExecutionState,
                                        GitBinding, Project, Suite)


def _repo(tmp_path):
    """A BARE remote — accepts pushes like a real hosting target;
    seeded via the app backend (dulwich), no git CLI."""
    from tests import git_helpers as gh
    src = tmp_path / "repo.git"
    gh.bare_repo(src)
    gh.seed_repo(str(src), tmp_path / "seed", {"f.txt": "x"}, "init")
    return src


def _env(app, repo):
    p = Project(name="P"); db.session.add(p); db.session.flush()
    b = GitBinding(project_id=p.id, name="b", url=str(repo),
                   ref="master", worktree_path=str(repo),
                   report_writable=True,
                   last_synced_sha="sha1", status="synced")
    db.session.add(b); db.session.flush()
    s = Suite(project_id=p.id, name="S"); db.session.add(s)
    db.session.flush()
    return p, b, s


def test_publish_to_repo_root(app, tmp_path):
    """Finalized report publishes under TestOrchestrator/Reports/<id>/
    at the repository root with a versioned manifest."""
    repo = _repo(tmp_path)
    with app.app_context():
        p, b, s = _env(app, repo)
        ex = dispatch.create_execution("m", s, binding=b,
                                       source_sha="sha1")
        ex.state = ExecutionState.COMPLETED
        ex.report_dir = str(tmp_path / "rep")
        Path(ex.report_dir).mkdir()
        (Path(ex.report_dir) / "j.xml").write_text("<testsuite/>")
        db.session.commit()
        r = gitsync.publish_report(ex.id)
        assert r.get("published")
        db.session.refresh(ex)
        assert ex.report_pub_status == "published"
        assert ex.report_pub_dir == f"TestOrchestrator/Reports/{ex.id}"
        # pushed content lives on the REMOTE ref — check via git show,
        # not the working tree (a non-bare repo isn't checkout-updated).
        from tests import git_helpers as gh
        out = gh.cli("-C", str(repo), "show",
             f"master:{ex.report_pub_dir}/manifest.json")
        assert out.returncode == 0, out.stderr
        d = json.loads(out.stdout)
        assert d["execution_id"] == ex.id and d["version"] == 1
        out2 = gh.cli("-C", str(repo), "show",
             f"master:{ex.report_pub_dir}/report/j.xml")
        assert out2.returncode == 0


def test_publication_failure_not_execution_failure(app, tmp_path):
    """A failed push marks publication failed — the execution stays
    COMPLETED; retry is available."""
    repo = _repo(tmp_path)
    with app.app_context():
        p, b, s = _env(app, repo)
        ex = dispatch.create_execution("m", s, binding=b)
        ex.state = ExecutionState.COMPLETED
        db.session.commit()
        # break the repo so push fails
        b.url = str(tmp_path / "nonexistent")
        db.session.commit()
        r = gitsync.publish_report(ex.id)
        assert r.get("error")
        db.session.refresh(ex)
        assert ex.report_pub_status == "failed"
        assert ex.state == ExecutionState.COMPLETED   # unchanged


def test_idempotent_retry_skips_unchanged(app, tmp_path):
    """Retrying a published report with unchanged content skips."""
    repo = _repo(tmp_path)
    with app.app_context():
        p, b, s = _env(app, repo)
        ex = dispatch.create_execution("m", s, binding=b)
        ex.state = ExecutionState.COMPLETED
        db.session.commit()
        gitsync.publish_report(ex.id)
        db.session.refresh(ex)
        sha1 = ex.report_pub_sha
        r = gitsync.publish_report(ex.id)
        assert r.get("skipped")


def test_delete_removes_only_its_report(app, tmp_path):
    """Deletion commits removal of ONLY this execution's dir; other
    reports and files survive."""
    repo = _repo(tmp_path)
    with app.app_context():
        p, b, s = _env(app, repo)
        ex = dispatch.create_execution("m", s, binding=b)
        ex.state = ExecutionState.COMPLETED
        db.session.commit()
        gitsync.publish_report(ex.id)
        from tests import git_helpers as gh
        out = gh.cli("-C", str(repo), "ls-tree",
                              "master", ex.report_pub_dir)
        assert ex.report_pub_dir in out.stdout
        r = gitsync.delete_report(ex.id)
        assert r.get("removed")
        from tests import git_helpers as gh
        out = gh.cli("-C", str(repo), "ls-tree",
                              "master", ex.report_pub_dir)
        assert out.stdout.strip() == ""   # dir removed
        # app record finalized (deleted) after remote removal
        out2 = gh.cli("-C", str(repo), "ls-tree",
                               "master", "f.txt")
        assert "f.txt" in out2.stdout   # unrelated preserved
        assert db.session.get(Execution, ex.id) is None


def test_delete_never_published_is_noop(app, tmp_path):
    """A never-published execution deletes cleanly — no repo write."""
    repo = _repo(tmp_path)
    with app.app_context():
        p, b, s = _env(app, repo)
        ex = dispatch.create_execution("m", s, binding=b)
        db.session.commit()
        r = gitsync.delete_report(ex.id)
        assert r.get("absent")


def test_deletion_blocks_republication(app, tmp_path):
    """Once deletion is requested, publication retries are refused —
    no recreating a doomed report."""
    repo = _repo(tmp_path)
    with app.app_context():
        p, b, s = _env(app, repo)
        ex = dispatch.create_execution("m", s, binding=b)
        ex.deletion_status = "pending"
        db.session.commit()
        r = gitsync.publish_report(ex.id)
        assert "deletion" in r["error"]


def test_unconfigured_destination_rejected(app, tmp_path):
    """A binding without report_writable refuses publication — clear
    unconfigured state, not a silent skip."""
    repo = _repo(tmp_path)
    with app.app_context():
        p, b, s = _env(app, repo)
        b.report_writable = False; db.session.commit()
        ex = dispatch.create_execution("m", s, binding=b)
        ex.state = ExecutionState.COMPLETED
        db.session.commit()
        r = gitsync.publish_report(ex.id)
        assert r["error"] == "unconfigured"
        db.session.refresh(ex)
        assert ex.report_pub_status == "failed"
        assert "write-back" in ex.report_pub_error


def test_tag_branch_rejected(app, tmp_path):
    """A tag/detached ref is not a valid report destination."""
    repo = _repo(tmp_path)
    with app.app_context():
        p, b, s = _env(app, repo)
        b.ref = "refs/tags/v1"; db.session.commit()
        ex = dispatch.create_execution("m", s, binding=b)
        ex.state = ExecutionState.COMPLETED
        db.session.commit()
        r = gitsync.publish_report(ex.id)
        assert r["error"] == "invalid branch"


def test_concurrent_publish_different_executions(app, tmp_path):
    """Two executions publishing from the same remote head both
    survive — no lost reports."""
    repo = _repo(tmp_path)
    with app.app_context():
        p, b, s = _env(app, repo)
        e1 = dispatch.create_execution("m", s, binding=b)
        e2 = dispatch.create_execution("m", s, binding=b)
        e1.state = e2.state = ExecutionState.COMPLETED
        db.session.commit()
        r1 = gitsync.publish_report(e1.id)
        r2 = gitsync.publish_report(e2.id)
        assert r1.get("published") and r2.get("published")
        from tests import git_helpers as gh
        for eid in (e1.id, e2.id):
            out = gh.cli("-C", str(repo), "ls-tree", "master",
                 f"TestOrchestrator/Reports/{eid}")
            assert f"Reports/{eid}" in out.stdout


def test_delete_uses_recorded_url_not_new_binding(app, tmp_path):
    """Publish, then change binding.url — deletion must target the
    ORIGINAL repo, never the newly configured one."""
    repo = _repo(tmp_path); repo2 = _repo(tmp_path / "r2")
    with app.app_context():
        p, b, s = _env(app, repo)
        ex = dispatch.create_execution("m", s, binding=b)
        ex.state = ExecutionState.COMPLETED
        db.session.commit()
        gitsync.publish_report(ex.id)
        # binding changed after publication
        b.url = str(repo2); db.session.commit()
        r = gitsync.delete_report(ex.id)
        assert r.get("removed")
        from tests import git_helpers as gh
        out = gh.cli("-C", str(repo), "ls-tree", "master",
             ex.report_pub_dir or "TestOrchestrator")
        assert ex.id not in out.stdout


def test_duplicate_publish_delivery_safe(app, tmp_path):
    """Duplicate outbox delivery is safe — second publish is a
    digest-identical skip, not a duplicate commit."""
    repo = _repo(tmp_path)
    with app.app_context():
        p, b, s = _env(app, repo)
        ex = dispatch.create_execution("m", s, binding=b)
        ex.state = ExecutionState.COMPLETED
        db.session.commit()
        gitsync.publish_report(ex.id)
        sha1 = ex.report_pub_sha
        r = gitsync.publish_report(ex.id)   # duplicate delivery
        assert r.get("skipped")
        db.session.refresh(ex)
        assert ex.report_pub_sha == sha1


def test_publish_failure_artifacts_remain_retrievable(tmp_path):
    """Publication failure must not disturb durable storage: a stored
    artifact stays 'stored' with its backend object intact — primary
    retrieval is independent of the optional publication path."""
    from tests.conftest import make_app, seed_users
    roots = tmp_path / "approved"
    roots.mkdir()
    app = make_app(tmp_path, "pub.db",
                   TO_ARTIFACT_ROOTS=[str(roots)])
    with app.app_context():
        db.create_all()
    seed_users(app)
    repo = _repo(tmp_path)
    with app.app_context():
        import json as _j
        from testorchestrator import storage
        from testorchestrator.execution import Artifact, ArtifactStore
        p, b, s = _env(app, repo)
        store = ArtifactStore(
            project_id=p.id, name="S", kind="local",
            config_json=_j.dumps({"root": str(roots)}))
        db.session.add(store); db.session.flush()
        ex = dispatch.create_execution("m", s, binding=b)
        ex.state = ExecutionState.COMPLETED
        rd = tmp_path / "rep"
        rd.mkdir()
        (rd / "j.xml").write_text("<testsuite/>")
        ex.report_dir = str(rd)
        from testorchestrator.results import sha256_file
        a = Artifact(execution_id=ex.id, kind="junit",
                     rel_path="j.xml", sha256=sha256_file(rd / "j.xml"),
                     size=13, mime="text/xml", mapped=True)
        db.session.add(a); db.session.flush()
        ref = storage.backend_for(store).put(
            rd / "j.xml", f"{p.id}/{ex.id}/1/j.xml")
        a.store_id, a.storage_ref = store.id, ref
        a.storage_state = "stored"
        # publication fails (broken remote) — storage must not move
        b.url = str(tmp_path / "nonexistent")
        db.session.commit()
        r = gitsync.publish_report(ex.id)
        assert r.get("error")
        db.session.refresh(a)
        assert a.storage_state == "stored"
        got = storage.backend_for(store).path(a.storage_ref)
        assert got.read_bytes() == b"<testsuite/>"
        db.session.refresh(ex)
        assert ex.state == ExecutionState.COMPLETED
