"""M16 Add Runtime wizard — runtime profiles, KRE included. The
katalon profile maps onto the KRE RuntimeConnection columns;
framework-adapted fields land in config_json; incompatible hidden
fields are dropped server-side."""

import json

from testorchestrator.extensions import db
from testorchestrator.execution import Runner, RuntimeConnection


def _runner(app, name="w1", kind="buildbot-worker"):
    with app.app_context():
        r = Runner(name=name, os_arch="linux/amd64",
                   connection_mode="remote", target_type=kind,
                   enabled=True, max_slots=2)
        db.session.add(r); db.session.commit()
        return r.id


def test_wizard_lists_frameworks_incl_kre(app, client):
    """Step 1 offers every framework including KRE (katalon)."""
    from tests.conftest import login
    _runner(app)
    login(client, "admin")
    body = client.get("/system/infrastructure/add-runtime").get_data(
        as_text=True)
    for fw in ("katalon", "pytest", "pytest-bdd", "behave", "robot",
               "jest", "playwright", "playwright-pytest", "cypress",
               "gtest", "postman", "bruno"):
        assert f'value="{fw}"' in body, fw
    assert "Engine" in body                    # postman engine field
    assert "does not install software" in body
    assert "Credential reference" in body      # kre secret select


def test_create_profile_pytest(app, client):
    """pytest profile: python_env lands in config_json + becomes
    executable_path; readiness starts not-checked."""
    from tests.conftest import login
    rid = _runner(app)
    login(client, "admin")
    client.post("/system/infrastructure/add-runtime", data={
        "framework": "pytest", "runner_id": rid,
        "name": "py-env", "cfg_python_env": "/opt/env/bin/python",
        "cfg_env": "A=1",
        # incompatible settings submitted but must be dropped
        "cfg_engine": "postman-cli", "cfg_sandbox": "developer_mode",
    })
    with app.app_context():
        rt = RuntimeConnection.query.one()
        assert rt.runtime_kind == "pytest"
        assert rt.readiness_state == "not-checked"
        assert rt.runner_id == rid
        cfg = rt.config()
        assert cfg["python_env"] == "/opt/env/bin/python"
        assert cfg["env"] == "A=1"
        assert "engine" not in cfg and "sandbox" not in cfg
        assert rt.executable_path == "/opt/env/bin/python"


def test_postman_requires_engine(app, client):
    """Postman cannot save without an explicit engine choice."""
    from tests.conftest import login
    rid = _runner(app)
    login(client, "admin")
    client.post("/system/infrastructure/add-runtime", data={
        "framework": "postman", "runner_id": rid,
        "name": "pm", "cfg_exec_path": "/usr/bin/newman"})
    with app.app_context():
        assert RuntimeConnection.query.count() == 0
    client.post("/system/infrastructure/add-runtime", data={
        "framework": "postman", "runner_id": rid, "name": "pm",
        "cfg_engine": "postman-cli",
        "cfg_exec_path": "/usr/local/bin/postman"})
    with app.app_context():
        rt = RuntimeConnection.query.one()
        assert rt.runtime_kind == "postman"
        assert rt.config()["engine"] == "postman-cli"


def test_unknown_framework_rejected(app, client):
    """Bogus/non-profile frameworks are refused."""
    from tests.conftest import login
    rid = _runner(app)
    login(client, "admin")
    for fw in ("kre", "bogus"):
        client.post("/system/infrastructure/add-runtime", data={
            "framework": fw, "runner_id": rid, "name": "x"})
    with app.app_context():
        assert RuntimeConnection.query.count() == 0


def test_katalon_wizard_creates_kre(app, client):
    """framework=katalon maps onto the KRE columns — exec path is
    required, credential_ref validated, concurrency parsed."""
    from tests.conftest import login
    from testorchestrator.secrets_store import store_secret
    rid = _runner(app)
    with app.app_context():
        store_secret(app, "kre-key", "runtime", "AK-123")
    login(client, "admin")
    # missing executable → refused
    client.post("/system/infrastructure/add-runtime", data={
        "framework": "katalon", "runner_id": rid, "name": "k"})
    # bad credential ref → refused
    client.post("/system/infrastructure/add-runtime", data={
        "framework": "katalon", "runner_id": rid, "name": "k",
        "cfg_exec_path": "/usr/local/bin/katalonc",
        "cfg_credential_ref": "nope-404"})
    # bad concurrency → refused
    client.post("/system/infrastructure/add-runtime", data={
        "framework": "katalon", "runner_id": rid, "name": "k",
        "cfg_exec_path": "/usr/local/bin/katalonc",
        "cfg_concurrency": "zero"})
    with app.app_context():
        assert RuntimeConnection.query.count() == 0
    # valid → kre runtime with the mapped columns
    client.post("/system/infrastructure/add-runtime", data={
        "framework": "katalon", "runner_id": rid, "name": "k",
        "cfg_exec_path": "/usr/local/bin/katalonc",
        "cfg_credential_ref": "kre-key",
        "cfg_credential_file": "/opt/to/cred/k.txt",
        "cfg_concurrency": "2"})
    with app.app_context():
        rt = RuntimeConnection.query.one()
        assert rt.runtime_kind == "kre"
        assert rt.executable_path == "/usr/local/bin/katalonc"
        assert rt.credential_ref == "kre-key"
        assert rt.credential_file == "/opt/to/cred/k.txt"
        assert rt.concurrency == 2
        assert rt.runner_id == rid


def test_project_associations_all_kinds(app, client):
    """allowed_projects editable for every runtime kind — for KRE
    this scopes where its managed credential may be delivered."""
    from tests.conftest import login
    from testorchestrator.execution import Project
    rid = _runner(app)
    with app.app_context():
        p = Project(name="P1", description="")
        db.session.add(p)
        rt = RuntimeConnection(
            name="k", runner_id=rid, transport="buildbot-worker",
            executable_path="/kre", runtime_kind="kre")
        rt2 = RuntimeConnection(
            name="j", runner_id=rid, transport="buildbot-worker",
            executable_path="/node", runtime_kind="jest")
        db.session.add_all([rt, rt2]); db.session.commit()
        pid, kre_id, jest_id = p.id, rt.id, rt2.id
    login(client, "admin")
    client.post(f"/system/runtimes/{jest_id}/projects",
                data={"project_ids": [pid]})
    with app.app_context():
        rt = db.session.get(RuntimeConnection, jest_id)
        assert json.loads(rt.allowed_projects) == [pid]
    client.post(f"/system/runtimes/{kre_id}/projects",
                data={"project_ids": [pid]})
    with app.app_context():
        rt = db.session.get(RuntimeConnection, kre_id)
        assert json.loads(rt.allowed_projects or "[]") == [pid]


def test_explicit_runtime_pick_enforces_project_scope(app):
    """A direct runtime_id submission is gated by allowed_projects
    on both the runtime and its bound target — a project-scoped
    caller cannot route a run (and for KRE its credential) through
    an association restricted to other projects."""
    from testorchestrator import dispatch
    from testorchestrator.execution import (
        DiscoveredItem, GitBinding, Project)
    rid = _runner(app)
    with app.app_context():
        pa = Project(name="PA")
        pb = Project(name="PB")
        db.session.add_all([pa, pb]); db.session.flush()
        b = GitBinding(project_id=pa.id, name="b", url="x",
                       worktree_path="/x", last_synced_sha="sha1",
                       status="synced")
        db.session.add(b); db.session.flush()
        item = DiscoveredItem(binding_id=b.id, project_id=pa.id,
                              sha="sha1", kind="suite",
                              path="Test Suites/S1", name="S1",
                              framework="katalon")
        db.session.add(item)
        rt = RuntimeConnection(
            name="k", runner_id=rid, transport="buildbot-worker",
            executable_path="/kre", runtime_kind="kre",
            allowed_projects=json.dumps([pb.id]))
        db.session.add(rt); db.session.commit()
        try:
            dispatch.create_execution(
                "tester", source_item=item, binding=b,
                source_sha="sha1",
                run_config={"runtime_id": rt.id})
            assert False, "expected project-scope refusal"
        except dispatch.DispatchError as exc:
            assert "restricted to other projects" in str(exc)
        item2 = DiscoveredItem(binding_id=b.id, project_id=pb.id,
                               sha="sha1", kind="suite",
                               path="Test Suites/S1", name="S1",
                               framework="katalon")
        db.session.add(item2); db.session.commit()
        ex2 = dispatch.create_execution(
            "tester", source_item=item2, binding=b,
            source_sha="sha1",
            run_config={"runtime_id": rt.id})
        assert ex2 is not None


def test_probe_blocked_runtime_not_dispatchable(app, client):
    """A non-KRE runtime whose probe found a missing dependency is
    excluded from pick_runtime; KRE runtimes are never gated."""
    from testorchestrator import dispatch
    from testorchestrator.execution import Execution, Project
    rid = _runner(app)
    with app.app_context():
        p = Project(name="P1", description="")
        db.session.add(p)
        db.session.flush()
        dead = RuntimeConnection(
            name="dead", runner_id=rid, transport="local",
            executable_path="/x", runtime_kind="pytest",
            readiness_state="missing-dependency")
        ok = RuntimeConnection(
            name="ok", runner_id=rid, transport="local",
            executable_path="/y", runtime_kind="pytest",
            readiness_state="ready-discovery")
        kre = RuntimeConnection(
            name="k", runner_id=rid, transport="local",
            executable_path="/z", runtime_kind="kre",
            readiness_state="missing-dependency")
        db.session.add_all([dead, ok, kre])
        db.session.commit()
        ex = Execution(project_id=p.id, source_sha="s",
                       report_dir="/tmp/r", snapshot_json="{}")
        db.session.add(ex)
        db.session.commit()
        runner = db.session.get(Runner, rid)
        picked = dispatch.pick_runtime(ex, runner)
        # dead + kre filtered differently: dead is probe-blocked,
        # kre is never gated by readiness — but pytest-kind 'ok'
        # comes first in creation order anyway? Verify the blocked
        # one specifically is skipped:
        assert picked is not dead
        assert dispatch._runtime_probe_blocked(dead) is True
        # KRE unchanged: readiness state never gates it
        assert dispatch._runtime_probe_blocked(kre) is False


def test_wizard_admin_only(app, client):
    """Non-admin roles cannot reach the wizard."""
    from tests.conftest import login
    _runner(app)
    login(client, "po")
    assert client.get("/system/infrastructure/add-runtime").status_code == 403
    assert client.post("/system/infrastructure/add-runtime",
                       data={}).status_code == 403
