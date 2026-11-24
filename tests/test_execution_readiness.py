"""M16 execution-level readiness — toolchain availability is NOT
execution readiness. A version answer never authorizes a run: the
(runtime, project) pair needs validated evidence, and dispatch
gates on it for real executions (native_collect stays on toolchain
readiness only — discovery ≠ execution)."""
import json

from testorchestrator import dispatch, execution_readiness
from testorchestrator.extensions import db
from testorchestrator.execution import (
    Execution, ExecutionState, FrameworkProject, GitBinding, Project,
    Runner, RuntimeConnection)


def _setup(app, kind="pytest", state="ready-discovery",
           fp_framework="pytest", fp_discovery="ok"):
    with app.app_context():
        r = Runner(name="w1", os_arch="linux/amd64",
                   connection_mode="remote",
                   target_type="buildbot-worker", enabled=True,
                   max_slots=2)
        p = Project(name="P", description="")
        db.session.add_all([r, p])
        db.session.flush()
        rt = RuntimeConnection(
            name="rt", runner_id=r.id, transport="buildbot-worker",
            executable_path="/opt/env/bin/python",
            runtime_kind=kind, readiness_state=state,
            probe_json=json.dumps({"workspace_write": "ok"}))
        db.session.add(rt)
        if fp_framework:
            b = GitBinding(project_id=p.id, name="b",
                           url="https://x/r.git")
            db.session.add(b)
            db.session.flush()
            fp = FrameworkProject(
                binding_id=b.id, project_id=p.id, name="fp",
                framework=fp_framework,
                discovery_status=fp_discovery)
            db.session.add(fp)
        db.session.commit()
        return r.id, p.id, rt.id


def _get(app, rid, pid, rtid):
    return (db.session.get(Runner, rid), db.session.get(Project, pid),
            db.session.get(RuntimeConnection, rtid))


def test_version_answer_is_not_exec_ready(app):
    """ready-discovery alone never authorizes execution."""
    rid, pid, rtid = _setup(app)
    with app.app_context():
        _, p, rt = _get(app, rid, pid, rtid)
        assert not execution_readiness.execution_ready(rt, p.id)
        failed = execution_readiness.validate_project(rt, p)
        assert failed == []
        assert rt.readiness_state == "ready-execution"
        assert execution_readiness.execution_ready(rt, p.id)


def test_missing_capability_and_unvalidated_project(app):
    """Negative toolchain or absent framework project → not ready."""
    rid, pid, rtid = _setup(app, state="missing-dependency")
    with app.app_context():
        _, p, rt = _get(app, rid, pid, rtid)
        failed = execution_readiness.validate_project(rt, p)
        assert any(f.startswith("toolchain") for f in failed)
        # toolchain verdict kept — not masked by a pair-level state
        assert rt.readiness_state == "missing-dependency"


def test_no_matching_framework_project(app):
    """Runtime kind must match a validated framework project."""
    rid, pid, rtid = _setup(app, fp_framework="cypress")
    with app.app_context():
        _, p, rt = _get(app, rid, pid, rtid)
        failed = execution_readiness.validate_project(rt, p)
        assert any(f.startswith("framework") for f in failed)
        assert rt.readiness_state == "project-validation-required"


def test_unvalidated_discovery_not_ready(app):
    rid, pid, rtid = _setup(app, fp_discovery="draft")
    with app.app_context():
        _, p, rt = _get(app, rid, pid, rtid)
        failed = execution_readiness.validate_project(rt, p)
        assert any(f.startswith("discovery") for f in failed)


def test_dispatch_gate_exec_vs_collect(app):
    """Execution without pair evidence is refused; native_collect
    (discovery) on the same runtime is toolchain-gated only."""
    rid, pid, rtid = _setup(app)
    with app.app_context():
        runner, p, rt = _get(app, rid, pid, rtid)
        ex = Execution(project_id=p.id, source_sha="s",
                       report_dir="/tmp/r",
                       snapshot_json=json.dumps(
                           {"run_config": {"runtime_id": rtid}}),
                       state=ExecutionState.QUEUED)
        db.session.add(ex)
        db.session.commit()
        ex = db.session.get(Execution, ex.id)
        # real execution: no validated pair → blocked + actionable
        block = dispatch._exec_ready_block(
            rt, p.id, {"runtime_id": rtid})
        assert "Validate for project" in block
        assert dispatch.pick_runtime(ex, runner) is None
        # discovery op: toolchain ready suffices
        assert dispatch._exec_ready_block(
            rt, p.id, {"native_collect": True}) == ""
        # after validation the same execution dispatch passes
        execution_readiness.validate_project(rt, p)
        assert dispatch.pick_runtime(ex, runner) is rt


def test_evidence_revoked_on_toolchain_change(app):
    """Probe re-run / profile edit clears pair evidence; association
    change prunes departed projects."""
    rid, pid, rtid = _setup(app)
    with app.app_context():
        _, p, rt = _get(app, rid, pid, rtid)
        execution_readiness.validate_project(rt, p)
        assert rt.readiness_state == "ready-execution"
        execution_readiness.clear_evidence(rt)
        rt.readiness_state = "ready-discovery"
        assert not execution_readiness.execution_ready(rt, p.id)


def test_association_prune_demotes(app):
    rid, pid, rtid = _setup(app)
    with app.app_context():
        _, p, rt = _get(app, rid, pid, rtid)
        execution_readiness.validate_project(rt, p)
        # remove the only project from scope
        rt.allowed_projects = json.dumps(["other-project"])
        execution_readiness.prune_projects(rt)
        assert rt.readiness_state == "ready-discovery"
        assert not execution_readiness.execution_ready(rt, p.id)


def test_validate_route(app, client):
    from tests.conftest import login
    rid, pid, rtid = _setup(app)
    login(client, "admin")
    r = client.post(f"/system/runtimes/{rtid}/validate-project",
                    data={"project_id": pid}, follow_redirects=True)
    assert r.status_code == 200
    assert b"ready-execution" in r.data
    with app.app_context():
        rt = db.session.get(RuntimeConnection, rtid)
        assert rt.readiness_state == "ready-execution"
    # KRE refused
    with app.app_context():
        kre = RuntimeConnection(name="k", runner_id=rid,
                                transport="local",
                                executable_path="/kre",
                                runtime_kind="kre")
        db.session.add(kre)
        db.session.commit()
        kre_id = kre.id
    r = client.post(f"/system/runtimes/{kre_id}/validate-project",
                    data={"project_id": pid}, follow_redirects=True)
    assert b"existing readiness flow" in r.data


def test_postman_engine_check(app):
    """postman requires a supported engine for execution readiness."""
    rid, pid, rtid = _setup(app, kind="postman",
                            fp_framework="postman")
    with app.app_context():
        _, p, rt = _get(app, rid, pid, rtid)
        failed = execution_readiness.validate_project(rt, p)
        assert any(f.startswith("engine") for f in failed)
        cfg = rt.config()
        cfg["engine"] = "newman"
        rt.config_json = json.dumps(cfg)
        failed = execution_readiness.validate_project(rt, p)
        assert failed == []
