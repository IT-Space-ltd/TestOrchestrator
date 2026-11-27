"""M9 durable artifact storage — approved roots, idempotent keys,
staging→stored lifecycle, retrieval fallback (boto3 absent → s3
gated honestly)."""

import json
import sys
import pytest
from pathlib import Path

from testorchestrator import storage
from testorchestrator.extensions import db
from testorchestrator.execution import (Artifact, ArtifactStore,
                                        Execution, Project)


def _app(tmp_path, roots):
    from tests.conftest import make_app, seed_users
    app = make_app(tmp_path, "storage.db",
                   TO_ARTIFACT_ROOTS=[str(roots)])
    with app.app_context():
        db.create_all()
    seed_users(app)
    return app


def _ex(app, tmp_path, root):
    """Execution + report_dir + one artifact row."""
    with app.app_context():
        p = Project(name="P", description="d")
        db.session.add(p); db.session.flush()
        rd = tmp_path / "w" / "Reports"
        (rd / "junit").mkdir(parents=True)
        (rd / "junit" / "r.xml").write_text("<testsuite/>")
        (rd / "log.txt").write_text("log")
        ex = Execution(project_id=p.id, source_sha="s",
                       report_dir=str(rd),
                       snapshot_json="{}")
        db.session.add(ex); db.session.flush()
        from testorchestrator.results import sha256_file
        for rel in ("junit/r.xml", "log.txt"):
            f = rd / rel
            db.session.add(Artifact(
                execution_id=ex.id, kind="junit", rel_path=rel,
                sha256=sha256_file(f), size=f.stat().st_size,
                mime="text/xml", mapped=True))
        db.session.commit()
        return p.id, ex.id, rd


def test_local_store_put_probe_verify(tmp_path):
    """Approved-root local store: tmp-write → rename → checksum
    verify → probe write/read/delete."""
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        st = ArtifactStore(project_id="p1", name="S", kind="local",
                           config_json=json.dumps(
                               {"root": str(roots / "a"),
                                "subdir": "proj"}))
        backend = storage.backend_for(st)
        src = tmp_path / "f.bin"
        src.write_bytes(b"x" * 100000)
        ref = backend.put(src, "p1/e1/1/f.bin")
        dst = backend.path(ref)
        assert dst.read_bytes() == src.read_bytes()
        ok, msg = backend.probe()
        assert ok, msg
        assert backend.delete(ref)


def test_root_containment_enforced(app, tmp_path):
    with app.app_context():
        outside = ArtifactStore(
            project_id="p1", name="S", kind="local",
            config_json=json.dumps(
                {"root": str(tmp_path / "unapproved")}))
        with pytest.raises(storage.StoreError, match="outside"):
            storage.backend_for(outside)


def test_s3_gated_without_boto3(app, monkeypatch):
    """Simulate a deployment where the (approved, server-side) boto3
    set is absent — e.g. an older/incomplete install: the capability
    gate must still produce the actionable readiness failure."""
    monkeypatch.setitem(sys.modules, "boto3", None)
    with app.app_context():
        st = ArtifactStore(project_id="p1", name="S", kind="s3",
                           config_json=json.dumps({"bucket": "b"}))
        with pytest.raises(storage.StoreError, match="boto3"):
            storage.backend_for(st)


def test_store_execution_artifacts(tmp_path):
    """End-to-end: staged artifacts → stored refs; staged files stay;
    failed file → failed state; rerun is idempotent."""
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        pid, exid, rd = _ex(app, tmp_path, roots)
        db.session.add(ArtifactStore(
            project_id=pid, name="S", kind="local", active=True,
            config_json=json.dumps({"root": str(roots)})))
        db.session.commit()
        ex = db.session.get(Execution, exid)
        out = storage.store_execution_artifacts(ex, rd)
        assert out == {"stored": 2, "failed": 0, "skipped": 0}
        a = Artifact.query.filter_by(execution_id=exid).first()
        assert a.storage_state == "stored"
        assert a.storage_ref.endswith(a.rel_path)
        assert a.attempt == 1
        assert a.store_id
        # durable copy exists under approved root; staging intact
        dst = roots / "p-nope"
        stored_file = next(roots.rglob("r.xml"))
        assert stored_file.is_file()
        assert (rd / "junit/r.xml").is_file()
        # idempotent rerun — same key, no duplicates
        out2 = storage.store_execution_artifacts(ex, rd)
        assert out2["stored"] == 2
        assert len(list(roots.rglob("r.xml"))) == 1


def test_retrieval_after_worker_removed(tmp_path):
    """Workspace staging removed (worker cleaned) → download serves
    the durable copy, checksum still enforced."""
    from tests.conftest import login
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        pid, exid, rd = _ex(app, tmp_path, roots)
        db.session.add(ArtifactStore(
            project_id=pid, name="S", kind="local", active=True,
            config_json=json.dumps({"root": str(roots)})))
        db.session.commit()
        ex = db.session.get(Execution, exid)
        storage.store_execution_artifacts(ex, rd)
        aid = Artifact.query.filter_by(
            execution_id=exid, rel_path="log.txt").first().id
    # worker workspace gone
    import shutil
    shutil.rmtree(rd)
    client = app.test_client()
    login(client, "admin")
    rv = client.get(f"/executions/{exid}/artifacts/{aid}")
    assert rv.status_code == 200
    assert rv.get_data() == b"log"


def test_partial_transfer_states(tmp_path):
    """One artifact's staged file missing → staged/skipped, the
    other still stores — no all-or-nothing failure."""
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        pid, exid, rd = _ex(app, tmp_path, roots)
        db.session.add(ArtifactStore(
            project_id=pid, name="S", kind="local", active=True,
            config_json=json.dumps({"root": str(roots)})))
        db.session.commit()
        (rd / "log.txt").unlink()          # file vanished pre-store
        ex = db.session.get(Execution, exid)
        out = storage.store_execution_artifacts(ex, rd)
        assert out == {"stored": 1, "failed": 0, "skipped": 1}
        states = {a.rel_path: a.storage_state for a in
                  Artifact.query.filter_by(execution_id=exid)}
        assert states["junit/r.xml"] == "stored"
        assert states["log.txt"] == "missing"   # actionable state


def test_corrupt_durable_copy_refused(tmp_path):
    """Tampered durable copy → download is refused (409), not
    silently served stale evidence."""
    from tests.conftest import login
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        pid, exid, rd = _ex(app, tmp_path, roots)
        db.session.add(ArtifactStore(
            project_id=pid, name="S", kind="local", active=True,
            config_json=json.dumps({"root": str(roots)})))
        db.session.commit()
        ex = db.session.get(Execution, exid)
        storage.store_execution_artifacts(ex, rd)
        aid = Artifact.query.filter_by(
            execution_id=exid, rel_path="log.txt").first().id
        durable = next(roots.rglob("log.txt"))
        durable.write_text("tampered")
    import shutil
    shutil.rmtree(rd)
    client = app.test_client()
    login(client, "admin")
    assert client.get(
        f"/executions/{exid}/artifacts/{aid}").status_code == 409


def test_key_traversal_refused(tmp_path):
    """A rel_path attempting escape resolves inside the store root
    only — containment checked on every write."""
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        st = ArtifactStore(project_id="p1", name="S", kind="local",
                           config_json=json.dumps(
                               {"root": str(roots)}))
        backend = storage.backend_for(st)
        src = tmp_path / "f"; src.write_text("x")
        with pytest.raises(storage.StoreError):
            backend.put(src, "../escape.bin")


def test_connection_route_does_not_persist(tmp_path):
    """Test Connection runs the probe on an UNSAVED store — the
    checklist is shown, nothing is persisted (§UI 3)."""
    from tests.conftest import login
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        pid, _, _ = _ex(app, tmp_path, roots)
    client = app.test_client()
    login(client, "admin")
    rv = client.post(f"/projects/{pid}/artifact-stores/test",
                     data={"kind": "local", "name": "T",
                           "root": str(roots)},
                     follow_redirects=True)
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "temporary write" in body
    assert "temporary delete" in body
    with app.app_context():
        assert ArtifactStore.query.count() == 0


def test_hidden_kind_fields_not_persisted(tmp_path):
    """Submitting kind=local alongside S3 fields persists only the
    local config — incompatible hidden settings are dropped
    server-side even if posted (§UI 9)."""
    from tests.conftest import login
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        pid, _, _ = _ex(app, tmp_path, roots)
    client = app.test_client()
    login(client, "admin")
    client.post(f"/projects/{pid}/artifact-stores/new",
                data={"kind": "local", "name": "L",
                      "root": str(roots),
                      "bucket": "evil", "prefix": "x/",
                      "endpoint_url": "http://bad",
                      "credential_ref": "cred"})
    with app.app_context():
        s = ArtifactStore.query.one()
        assert sorted(s.config()) == ["root", "subdir"]
        assert s.credential_ref == ""


def test_delete_retires_referenced_store(tmp_path):
    """Removing a destination that stored artifacts still reference
    retires it — config preserved, retrieval intact, no new writes
    (§UI 4)."""
    from tests.conftest import login
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        pid, exid, rd = _ex(app, tmp_path, roots)
        db.session.add(ArtifactStore(
            project_id=pid, name="S", kind="local", active=True,
            config_json=json.dumps({"root": str(roots)})))
        db.session.commit()
        ex = db.session.get(Execution, exid)
        storage.store_execution_artifacts(ex, rd)
        sid = ArtifactStore.query.one().id
        aid = Artifact.query.filter_by(execution_id=exid).first().id
    import shutil
    shutil.rmtree(rd)
    client = app.test_client()
    login(client, "admin")
    client.post(f"/artifact-stores/{sid}/delete")
    with app.app_context():
        s = db.session.get(ArtifactStore, sid)
        assert s is not None and s.retired and not s.active
        # retired store never selected for new transfers
        assert ArtifactStore.query.filter_by(
            project_id=pid, active=True).first() is None
    # historical artifact still retrievable through kept config
    rv = client.get(f"/executions/{exid}/artifacts/{aid}")
    assert rv.status_code == 200
    # retired cannot be re-activated
    client.post(f"/artifact-stores/{sid}/toggle")
    with app.app_context():
        assert not db.session.get(ArtifactStore, sid).active


def test_unreferenced_store_deletes(tmp_path):
    """A store nothing references is removed outright."""
    from tests.conftest import login
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        pid, _, _ = _ex(app, tmp_path, roots)
        db.session.add(ArtifactStore(
            project_id=pid, name="S", kind="local",
            config_json=json.dumps({"root": str(roots)})))
        db.session.commit()
        sid = ArtifactStore.query.one().id
    client = app.test_client()
    login(client, "admin")
    client.post(f"/artifact-stores/{sid}/delete")
    with app.app_context():
        assert db.session.get(ArtifactStore, sid) is None


def test_storage_tab_guided_form(tmp_path):
    """Storage tab renders the guided flow: type choice, per-kind
    field groups, test-connection step, publication separation."""
    from tests.conftest import login
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        pid, _, _ = _ex(app, tmp_path, roots)
    client = app.test_client()
    login(client, "admin")
    rv = client.get(f"/projects/{pid}?tab=storage")
    body = rv.get_data(as_text=True)
    assert rv.status_code == 200
    assert 'data-kind="local"' in body
    assert 'data-kind="mounted"' in body
    assert 'data-kind="object"' in body
    for provider in ("amazon", "azure", "google", "manual"):
        assert f'data-provider="{provider}"' in body
    assert "Object Storage Provider" in body
    assert "Test connection" in body
    assert "Git publication" in body
    assert "disabled" in body            # hidden groups are disabled
    assert "artifact-stores/test" in body


def test_mounted_absent_share_refused(tmp_path):
    """A mounted destination whose share is absent must not write
    into the underlying mount-point directory (§4)."""
    roots = tmp_path / "approved"
    mount = tmp_path / "plaindir"
    mount.mkdir()
    app = _app(tmp_path, roots)
    with app.app_context():
        app.config["TO_MOUNTED_ROOTS"] = [str(tmp_path)]
        st = ArtifactStore(project_id="p1", name="S",
                           kind="mounted",
                           config_json=json.dumps({"root": str(mount)}))
        with pytest.raises(storage.StoreError,
                           match="not a mount point"):
            storage.backend_for(st)


def test_capture_policy_snapshot_and_enforce(tmp_path):
    """Excluded categories are not registered as artifacts but are
    recorded in the sealed manifest; policy comes from the
    execution snapshot, not live project state (§5)."""
    from testorchestrator import dispatch
    from testorchestrator.capture import normalize_policy
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        pid, exid, rd = _ex(app, tmp_path, roots)
        (rd / "shot.png").write_bytes(b"PNG")
        (rd / "vid.mp4").write_bytes(b"V")
        ex = db.session.get(Execution, exid)
        pol = normalize_policy({"screenshots": False, "videos": False})
        snap = ex.snapshot()
        snap.setdefault("run_config", {})["capture_policy"] = pol
        ex.snapshot_json = json.dumps(snap)
        db.session.commit()
        dispatch._collect(ex, rd, rd)
        kinds = {a.rel_path for a in
                 Artifact.query.filter_by(execution_id=exid)}
        assert "shot.png" not in kinds
        assert "vid.mp4" not in kinds
        assert "junit/r.xml" in kinds
        man = json.loads((rd / "manifest.json").read_text())
        excl = {e["rel_path"] for e in man["excluded"]}
        assert {"shot.png", "vid.mp4"} <= excl


def test_reports_category_cannot_be_disabled():
    """Machine-readable results are required — a policy that tries
    to disable them normalizes back to enabled (§5)."""
    from testorchestrator.capture import normalize_policy
    pol = normalize_policy({"reports": False, "videos": False})
    assert pol["reports"] is True
    assert pol["videos"] is False


def test_capture_policy_route(tmp_path):
    """Route saves normalized policy; reports stays on; audit
    records it (§5, §9 UI)."""
    from tests.conftest import login
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        pid, _, _ = _ex(app, tmp_path, roots)
    client = app.test_client()
    login(client, "admin")
    rv = client.post(f"/projects/{pid}/capture-policy",
                     data={"cat_videos": "1", "cat_reports": "0"},
                     follow_redirects=True)
    assert rv.status_code == 200
    with app.app_context():
        p = db.session.get(Project, pid)
        pol = p.capture_policy()
        assert pol["reports"] is True     # forced on
        assert pol["videos"] is True
        assert pol["screenshots"] is False  # unchecked → off


def test_store_routes_require_edit_role(tmp_path):
    """test/new/probe/toggle/delete all refuse non-edit roles
    (§7)."""
    from tests.conftest import login
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        pid, _, _ = _ex(app, tmp_path, roots)
        db.session.add(ArtifactStore(
            project_id=pid, name="S", kind="local",
            config_json=json.dumps({"root": str(roots)})))
        db.session.commit()
        sid = ArtifactStore.query.one().id
    client = app.test_client()
    login(client, "po")          # project-owner: read-only role
    for url in (f"/projects/{pid}/artifact-stores/test",
                f"/projects/{pid}/artifact-stores/new",
                f"/artifact-stores/{sid}/probe",
                f"/artifact-stores/{sid}/toggle",
                f"/artifact-stores/{sid}/delete",
                f"/projects/{pid}/capture-policy"):
        assert client.post(url, data={}).status_code == 403, url


# ------------------------------------------------------------------
# object-store download staging — bounded resource safeguards (§5)
# ------------------------------------------------------------------

class _ObjBackend:
    """Object-store stand-in: open() only, no .path() — drives the
    staging fallback exactly like _S3Store."""
    def __init__(self, data):
        self.data = data
    def open(self, ref):
        import io
        return io.BytesIO(self.data)
    def delete(self, ref):
        return True


def _staged_dl_app(tmp_path, data=b"<testsuite/>", size=None):
    """App + execution + artifact stored in an object store, staged
    files already gone → the download must take the staging path."""
    from tests.conftest import make_app, seed_users, login
    roots = tmp_path / "approved"
    app = make_app(tmp_path, "dl.db", TO_ARTIFACT_ROOTS=[str(roots)])
    with app.app_context():
        db.create_all()
    seed_users(app)
    with app.app_context():
        p = Project(name="P", description="d")
        db.session.add(p); db.session.flush()
        rd = tmp_path / "gone"                     # never created
        ex = Execution(project_id=p.id, source_sha="s",
                       report_dir=str(rd), snapshot_json="{}")
        db.session.add(ex); db.session.flush()
        from testorchestrator.results import sha256_file
        src = tmp_path / "r.xml"
        src.write_bytes(data)
        st = ArtifactStore(project_id=p.id, name="obj", kind="s3",
                           config_json=json.dumps({"bucket": "b"}))
        db.session.add(st); db.session.flush()
        a = Artifact(execution_id=ex.id, kind="junit",
                     rel_path="r.xml", sha256=sha256_file(src),
                     size=size if size is not None else len(data),
                     mime="text/xml", mapped=True,
                     store_id=st.id, storage_ref="k/r.xml",
                     storage_state="stored")
        db.session.add(a); db.session.commit()
        ex_id, a_id = ex.id, a.id
    c = app.test_client()
    login(c, "admin")
    return app, c, ex_id, a_id


def test_obj_download_staged_and_cleaned(tmp_path, monkeypatch):
    """Staging path serves bytes; temp file removed after close and
    lives under instance/.dl-staging — never in a report dir or an
    approved root (can't be collected as an artifact)."""
    app, c, ex_id, a_id = _staged_dl_app(tmp_path)
    monkeypatch.setattr(storage, "backend_for",
                        lambda st: _ObjBackend(b"<testsuite/>"))
    r = c.get(f"/executions/{ex_id}/artifacts/{a_id}")
    assert r.status_code == 200 and r.data == b"<testsuite/>"
    d = Path(app.instance_path) / ".dl-staging"
    assert d.parent == Path(app.instance_path)
    assert list(d.iterdir()) == []            # cleaned on close


def test_obj_download_oversize_refused(tmp_path, monkeypatch):
    """Object larger than the registered size → 409, not unbounded
    buffering."""
    app, c, ex_id, a_id = _staged_dl_app(
        tmp_path, data=b"x" * 100, size=10)
    monkeypatch.setattr(storage, "backend_for",
                        lambda st: _ObjBackend(b"x" * 100))
    r = c.get(f"/executions/{ex_id}/artifacts/{a_id}")
    assert r.status_code == 409
    d = Path(app.instance_path) / ".dl-staging"
    assert not d.exists() or list(d.iterdir()) == []


def test_obj_download_checksum_mismatch(tmp_path, monkeypatch):
    """Corrupted durable copy → 409 + temp removed."""
    app, c, ex_id, a_id = _staged_dl_app(tmp_path)
    monkeypatch.setattr(storage, "backend_for",
                        lambda st: _ObjBackend(b"TAMPERED!"))
    r = c.get(f"/executions/{ex_id}/artifacts/{a_id}")
    assert r.status_code == 409
    d = Path(app.instance_path) / ".dl-staging"
    assert not d.exists() or list(d.iterdir()) == []


def test_obj_download_stale_sweep(tmp_path, monkeypatch):
    """Abandoned temp files (crash leftovers) are swept on the next
    staging pass."""
    app, c, ex_id, a_id = _staged_dl_app(tmp_path)
    monkeypatch.setattr(storage, "backend_for",
                        lambda st: _ObjBackend(b"<testsuite/>"))
    import os, time
    from testorchestrator.portal import routes as pr
    with app.app_context():
        d = pr._dl_staging_dir()
        stale = d / ".dl-abandoned"
        stale.write_bytes(b"old")
        old = time.time() - pr._DL_STAGE_MAX_AGE_S - 10
        os.utime(stale, (old, old))
    r = c.get(f"/executions/{ex_id}/artifacts/{a_id}")
    assert r.status_code == 200
    assert not stale.exists()                 # swept


def test_obj_download_concurrency_cap(tmp_path, monkeypatch):
    """Semaphore exhaustion → bounded 503 rather than unbounded
    worker-thread occupation."""
    app, c, ex_id, a_id = _staged_dl_app(tmp_path)
    monkeypatch.setattr(storage, "backend_for",
                        lambda st: _ObjBackend(b"<testsuite/>"))
    from testorchestrator.portal import routes as pr
    class _Never:
        def acquire(self, timeout=None):
            return False
        def release(self):
            pass
    monkeypatch.setattr(pr, "_DL_STAGE_SEM", _Never())
    r = c.get(f"/executions/{ex_id}/artifacts/{a_id}")
    assert r.status_code == 503


def test_blocking_storage_op_is_bounded(tmp_path, monkeypatch):
    """§storage-4: a storage I/O op stuck on a dead share cannot
    occupy request capacity indefinitely — run_bounded surfaces a
    timeout error promptly (the parked worker is bounded at pool
    size). Verified with a sleeping op standing in for an
    uninterruptible NFS block."""
    import time
    from testorchestrator.storage import run_bounded, StoreError
    t0 = time.time()
    with _app(tmp_path, tmp_path / "r").app_context():
        with pytest.raises(StoreError, match="timed out"):
            run_bounded(lambda: time.sleep(30), timeout=0.5)
    assert time.time() - t0 < 10


def test_s3_non_tls_endpoint_refused(tmp_path):
    """http:// endpoints are refused by default — TLS is required;
    a test-only config flag is the only override (§7)."""
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        st = ArtifactStore(project_id="p1", name="S", kind="s3",
                           config_json=json.dumps(
                               {"bucket": "b",
                                "endpoint_url": "http://minio:9000"}))
        with pytest.raises(storage.StoreError, match="non-TLS"):
            storage.backend_for(st)
        # test-only override passes the endpoint check; with the
        # approved boto3 set installed the backend now constructs
        # (client construction performs no network I/O)
        app.config["TO_S3_ALLOW_INSECURE_ENDPOINTS"] = True
        backend = storage.backend_for(st)
        assert backend.bucket == "b"


# ---------- provider selector (§8) ----------

def test_azure_string_to_sign_matches_documented_example():
    """Shared-Key string-to-sign constructed byte-for-byte per the
    Microsoft-published sample (Authorize with Shared Key): GET
    mycontainer?restype=container&comp=metadata."""
    sts = storage._AzureStore._string_to_sign(
        "myaccount", "GET",
        "https://myaccount.blob.core.windows.net/mycontainer"
        "?restype=container&comp=metadata",
        {"x-ms-date": "Fri, 17 Nov 2005 01:37:34 GMT",
         "x-ms-version": "2009-09-19"})
    assert sts == (
        "GET\n\n\n\n\n\n\n\n\n\n\n\n"
        "x-ms-date:Fri, 17 Nov 2005 01:37:34 GMT\n"
        "x-ms-version:2009-09-19\n"
        "/myaccount/mycontainer\n"
        "comp:metadata\n"
        "restype:container")


def test_azure_sign_is_hmac_sha256():
    import base64
    import hmac as _h
    key = base64.b64encode(b"k" * 32).decode()
    sig = storage._AzureStore._sign(
        "acct", key, "PUT",
        "https://acct.blob.core.windows.net/c/b",
        {"x-ms-date": "d", "x-ms-version": "2020-10-02",
         "Content-Length": "5", "x-ms-blob-type": "BlockBlob"})
    sts = storage._AzureStore._string_to_sign(
        "acct", "PUT",
        "https://acct.blob.core.windows.net/c/b",
        {"x-ms-date": "d", "x-ms-version": "2020-10-02",
         "Content-Length": "5", "x-ms-blob-type": "BlockBlob"})
    assert sig == base64.b64encode(_h.new(
        base64.b64decode(key), sts.encode(),
        storage.hashlib.sha256).digest()).decode()


def test_gcs_store_pins_interop_endpoint(tmp_path):
    """GCS routes through boto3 pinned to the documented XML-API
    interop endpoint, path-style, region auto."""
    app = _app(tmp_path, tmp_path / "r")
    with app.app_context():
        st = ArtifactStore(project_id="p1", name="S", kind="gcs",
                           config_json=json.dumps({"bucket": "b"}))
        backend = storage.backend_for(st)
        assert backend.bucket == "b"
        assert backend.cfg["endpoint_url"] == \
            "https://storage.googleapis.com"
        assert backend.cfg["path_style"] is True
        assert backend.cfg["region"] == "auto"


def test_azure_store_validation(tmp_path):
    """Azure requires endpoint+container, a supported auth mode,
    TLS (same policy as s3), and the matching credential."""
    app = _app(tmp_path, tmp_path / "r")
    with app.app_context():
        base = dict(project_id="p1", name="S", kind="azure")
        with pytest.raises(storage.StoreError,
                           match="container"):
            storage.backend_for(ArtifactStore(
                **base, config_json=json.dumps(
                    {"account_url": "https://a.blob.core.windows.net"})))
        with pytest.raises(storage.StoreError,
                           match="auth mode"):
            storage.backend_for(ArtifactStore(
                **base, config_json=json.dumps(
                    {"account_url": "https://a.blob.core.windows.net",
                     "container": "c", "auth_mode": "oauth"})))
        with pytest.raises(storage.StoreError, match="non-TLS"):
            storage.backend_for(ArtifactStore(
                **base, config_json=json.dumps(
                    {"account_url": "http://a.blob.core.windows.net",
                     "container": "c", "auth_mode": "sas"})))


def test_store_form_provider_mapping(tmp_path):
    """The provider selector maps to backend kinds — amazon/gcs/s3
    get bucket configs, azure gets account_url/container/auth."""
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        pid, _, _ = _ex(app, tmp_path, roots)
    client = app.test_client()
    from tests.conftest import login
    login(client, "admin")

    def post(data):
        return client.post(
            f"/projects/{pid}/artifact-stores/new", data=data)

    post({"kind": "object", "provider": "amazon", "name": "a1",
          "bucket": "bkt", "region": "eu-central-1"})
    post({"kind": "object", "provider": "azure", "name": "a2",
          "account_url": "https://a.blob.core.windows.net",
          "container": "cont", "auth_mode": "sas",
          "credential_ref": "az-sas"})
    post({"kind": "object", "provider": "google", "name": "a3",
          "bucket": "bkt2", "credential_ref": "gcs-hmac"})
    post({"kind": "object", "provider": "manual", "name": "a4",
          "bucket": "bkt3", "endpoint_url": "https://minio.local"})
    # forged unknown provider is refused server-side
    post({"kind": "object", "provider": "oracle", "name": "bad",
          "bucket": "x"})
    with app.app_context():
        stores = {s.name: s for s in ArtifactStore.query.all()}
        assert stores["a1"].kind == "s3"
        assert stores["a1"].config()["provider"] == "amazon"
        assert stores["a2"].kind == "azure"
        assert stores["a2"].config()["auth_mode"] == "sas"
        assert stores["a2"].credential_ref == "az-sas"
        assert stores["a3"].kind == "gcs"
        assert stores["a3"].credential_ref == "gcs-hmac"
        assert stores["a4"].kind == "s3"
        assert stores["a4"].config()["provider"] == "manual"
        assert "bad" not in stores


def test_store_edit_reopens_and_preserves_provider(tmp_path):
    """Edit posts the same provider fields; kind is immutable and a
    blank credential_ref keeps the saved reference."""
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        pid, _, _ = _ex(app, tmp_path, roots)
        st = ArtifactStore(
            project_id=pid, name="S", kind="azure",
            config_json=json.dumps(
                {"account_url": "https://a.blob.core.windows.net",
                 "container": "c1", "prefix": "p",
                 "auth_mode": "account_key", "provider": "azure"}),
            credential_ref="az-key")
        db.session.add(st); db.session.commit()
        sid = st.id
    client = app.test_client()
    from tests.conftest import login
    login(client, "admin")
    client.post(f"/artifact-stores/{sid}/edit", data={
        "kind": "object", "provider": "azure", "name": "S2",
        "account_url": "https://a.blob.core.windows.net",
        "container": "c2", "auth_mode": "sas",
        "credential_ref": ""})
    with app.app_context():
        st = db.session.get(ArtifactStore, sid)
        assert st.name == "S2"
        assert st.config()["container"] == "c2"
        assert st.config()["auth_mode"] == "sas"
        assert st.credential_ref == "az-key"      # blank = unchanged
    # kind cannot change under existing refs
    client.post(f"/artifact-stores/{sid}/edit", data={
        "kind": "local", "name": "S3", "root": "/x"})
    with app.app_context():
        st = db.session.get(ArtifactStore, sid)
        assert st.kind == "azure" and st.name == "S2"


def test_store_edit_legacy_s3_reopens_as_manual(tmp_path):
    """Pre-provider s3 rows (no cfg.provider) reopen in the Other
    (Manual) mode — no destructive migration of stored configs."""
    roots = tmp_path / "approved"
    app = _app(tmp_path, roots)
    with app.app_context():
        pid, _, _ = _ex(app, tmp_path, roots)
        st = ArtifactStore(
            project_id=pid, name="S", kind="s3",
            config_json=json.dumps({"bucket": "b", "prefix": "",
                                    "endpoint_url":
                                        "https://minio.local"}))
        db.session.add(st); db.session.commit()
        sid = st.id
    client = app.test_client()
    from tests.conftest import login
    login(client, "admin")
    client.post(f"/artifact-stores/{sid}/edit", data={
        "kind": "object", "provider": "manual", "name": "S",
        "bucket": "b", "endpoint_url": "https://minio2.local",
        "path_style": "1"})
    with app.app_context():
        st = db.session.get(ArtifactStore, sid)
        assert st.kind == "s3"
        cfg = st.config()
        assert cfg["endpoint_url"] == "https://minio2.local"
        assert cfg["path_style"] is True
