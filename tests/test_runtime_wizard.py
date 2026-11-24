"""M16 Add Runtime wizard — non-KRE runtime profiles. KRE stays
out of the flow; framework-adapted fields land in config_json;
incompatible hidden fields are dropped server-side."""

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


def test_wizard_lists_frameworks_no_kre(app, client):
    """Step 1 offers all non-KRE frameworks — never KRE."""
    from tests.conftest import login
    _runner(app)
    login(client, "admin")
    body = client.get("/system/infrastructure/add-runtime").get_data(
        as_text=True)
    for fw in ("pytest", "pytest-bdd", "behave", "robot", "jest",
               "playwright", "playwright-pytest", "cypress",
               "gtest", "postman", "bruno"):
        assert f'value="{fw}"' in body, fw
    assert 'value="katalon"' not in body
    assert 'value="kre"' not in body
    assert "Engine" in body                    # postman engine field
    assert "does not install software" in body


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


def test_katalon_rejected(app, client):
    """framework=katalon (or kre) is refused — KRE keeps its own
    flow, untouched (§1 hard boundary)."""
    from tests.conftest import login
    rid = _runner(app)
    login(client, "admin")
    for fw in ("katalon", "kre", "bogus"):
        client.post("/system/infrastructure/add-runtime", data={
            "framework": fw, "runner_id": rid, "name": "x"})
    with app.app_context():
        assert RuntimeConnection.query.count() == 0


def test_project_associations_non_kre_only(app, client):
    """allowed_projects editable for non-KRE; a kre runtime is
    refused (its association path stays unchanged)."""
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
        assert json.loads(rt.allowed_projects or "[]") == []


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
