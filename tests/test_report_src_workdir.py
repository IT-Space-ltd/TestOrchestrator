"""D-ARTIFACT-SUBDIR: report_src must follow the execution workdir —
a framework running in a subdirectory (bruno executes from the
collection root) writes Reports there; uploading src/Reports collected
nothing and the run was falsely INCOMPLETE with zero artifacts."""

def test_report_src_follows_workdir():
    class _Ex:
        def run_config(self):
            return {}

        def snapshot(self):
            return {"run_config": {}}

    from testorchestrator.buildbot_cfg import node_exec_spec
    # default: no override — src/Reports
    spec = node_exec_spec(_Ex(), "npx", ["jest"])
    assert spec["report_src"] == "src/Reports"
    # bruno-style subdirectory override — reports land in the subdir
    spec = node_exec_spec(_Ex(), "/usr/local/bin/bru", ["run"],
                          workdir="build/src/bruno")
    assert spec["report_src"] == "src/bruno/Reports", spec["report_src"]
    # deeper nesting (monorepo collection root)
    spec = node_exec_spec(_Ex(), "npx", ["jest"],
                          workdir="build/src/services/gamma")
    assert spec["report_src"] == "src/services/gamma/Reports"

def test_node_subdir_workdir_dispatch(app, monkeypatch, tmp_path):
    """D-NODE-SUBDIR-WORKDIR: for a framework project rooted in a repo
    subdirectory (fp.test_roots=['jest']), the exec workdir must follow
    the project root, the spec path must be rebased, and the lockfile
    check must resolve inside the project dir — not the repo root."""
    import json
    from testorchestrator import buildbot_cfg, dispatch as d
    from testorchestrator import settings as _s
    from testorchestrator.adapters.buildbot import BuildbotAdapter
    from testorchestrator.execution import (DiscoveredItem, Execution,
        FrameworkProject, GitBinding, OutboxEvent, Project, Runner,
        RuntimeConnection)
    from testorchestrator.extensions import db
    from tests.test_buildbot_dispatch import _BBProbe

    stub = _BBProbe()
    monkeypatch.setattr(BuildbotAdapter, "from_settings",
                        classmethod(lambda cls: stub))
    monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
    with app.app_context():
        _s.update({"buildbot_endpoint": "http://stub",
                   "buildbot_home": str(tmp_path)})
        r = Runner(name="bb-t", connection_mode="local",
                   target_type="local", os_arch="linux", max_slots=2)
        db.session.add(r)
        db.session.flush()
        p = Project(name="mono")
        db.session.add(p)
        db.session.flush()
        wt = tmp_path / "wt"
        (wt / "jest").mkdir(parents=True)
        (wt / "jest" / "package-lock.json").write_text("{}")
        b = GitBinding(project_id=p.id, name="b", url="/x",
                       worktree_path=str(wt), last_synced_sha="abc")
        db.session.add(b)
        db.session.flush()
        fp = FrameworkProject(project_id=p.id, binding_id=b.id,
                              framework="jest", name="jest",
                              discovery_status="ok", discovered_sha="abc")
        fp.test_roots_json = json.dumps(["jest"])
        db.session.add(fp)
        db.session.flush()
        rt = RuntimeConnection(
            name="rt-jest", runner_id=r.id, executable_path="npx",
            enabled=True, runtime_kind="jest",
            readiness_state="ready-execution",
            config_json=json.dumps({"_exec_ready": {p.id: {"ok": 1}}}))
        db.session.add(rt)
        db.session.flush()
        di = DiscoveredItem(project_id=p.id, binding_id=b.id,
                            framework_project_id=fp.id, framework="jest",
                            kind="suite", path="jest/smoke.test.js",
                            name="smoke", sha="s", order_idx=0,
                            selectable=True, granularity="file",
                            node_id="jest/smoke.test.js")
        db.session.add(di)
        db.session.commit()
        ex = d.create_execution(
            "u", None, run_config={"framework": "jest",
                                   "runtime_id": rt.id},
            source_item=db.session.get(DiscoveredItem, di.id))
        ev = OutboxEvent.query.filter(
            OutboxEvent.kind == "orchestrator-dispatch",
            OutboxEvent.payload_json.contains(ex.id)).first()
        d._handle_event(ev)
        db.session.refresh(ex)
        assert ex.error_text in (None, ""), \
            f"dispatch failed: {ex.error_text}"
        assert len(stub.submits) == 1, f"submits: {len(stub.submits)}"
        _, _, props = stub.submits[0]
        spec = json.loads(props["exec_spec"])
        assert spec["exec_workdir"] == "build/src/jest", spec["exec_workdir"]
        assert spec["report_src"] == "src/jest/Reports"
        joined = " ".join(str(a) for a in spec["args"])
        assert "smoke.test.js" in joined
        assert "jest/smoke.test.js" not in joined
        assert spec.get("deps_argv"), "npm ci step missing"

def test_node_subdir_collect_script_path(app, monkeypatch, tmp_path):
    """Regression: the native collector is staged at the src root while
    the exec cwd is the framework subdirectory — the .to_collect.js
    reference must be relative to the actual workdir, or node fails
    with MODULE_NOT_FOUND and the collect ends with no result data."""
    import json
    from testorchestrator import buildbot_cfg, dispatch as d
    from testorchestrator import settings as _s
    from testorchestrator.adapters.buildbot import BuildbotAdapter
    from testorchestrator.execution import (DiscoveredItem,
        FrameworkProject, GitBinding, OutboxEvent, Project, Runner,
        RuntimeConnection)
    from testorchestrator.extensions import db
    from tests.test_buildbot_dispatch import _BBProbe

    stub = _BBProbe()
    monkeypatch.setattr(BuildbotAdapter, "from_settings",
                        classmethod(lambda cls: stub))
    monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
    with app.app_context():
        _s.update({"buildbot_endpoint": "http://stub",
                   "buildbot_home": str(tmp_path)})
        r = Runner(name="bb-t", connection_mode="local",
                   target_type="local", os_arch="linux", max_slots=2)
        db.session.add(r)
        db.session.flush()
        p = Project(name="mono")
        db.session.add(p)
        db.session.flush()
        wt = tmp_path / "wt"
        (wt / "jest").mkdir(parents=True)
        (wt / "jest" / "package-lock.json").write_text("{}")
        b = GitBinding(project_id=p.id, name="b", url="/x",
                       worktree_path=str(wt), last_synced_sha="abc")
        db.session.add(b)
        db.session.flush()
        fp = FrameworkProject(project_id=p.id, binding_id=b.id,
                              framework="jest", name="jest",
                              discovery_status="ok", discovered_sha="abc")
        fp.test_roots_json = json.dumps(["jest"])
        db.session.add(fp)
        db.session.flush()
        rt = RuntimeConnection(
            name="rt-jest", runner_id=r.id, executable_path="npx",
            enabled=True, runtime_kind="jest",
            readiness_state="ready-execution",
            config_json=json.dumps({"_exec_ready": {p.id: {"ok": 1}}}))
        db.session.add(rt)
        db.session.flush()
        di = DiscoveredItem(project_id=p.id, binding_id=b.id,
                            framework_project_id=fp.id, framework="jest",
                            kind="suite", path="jest/smoke.test.js",
                            name="smoke", sha="s", order_idx=0,
                            selectable=True, granularity="file",
                            node_id="jest/smoke.test.js")
        db.session.add(di)
        db.session.commit()
        ex = d.create_execution(
            "u", None, binding=db.session.get(GitBinding, b.id),
            run_config={"framework": "jest",
                        "runtime_id": rt.id,
                        "fp_id": fp.id,
                        "native_collect": True,
                        "collect_roots": ["jest"]})
        ev = OutboxEvent.query.filter(
            OutboxEvent.kind == "orchestrator-dispatch",
            OutboxEvent.payload_json.contains(ex.id)).first()
        d._handle_event(ev)
        db.session.refresh(ex)
        assert ex.error_text in (None, ""), \
            f"dispatch failed: {ex.error_text}"
        assert len(stub.submits) == 1, f"submits: {len(stub.submits)}"
        _, _, props = stub.submits[0]
        spec = json.loads(props["exec_spec"])
        assert spec["exec_workdir"] == "build/src/jest", spec["exec_workdir"]
        args = [str(a) for a in spec["args"]]
        assert args[0] == "../.to_collect.js", args
        joined = " ".join(args)
        # the rebased collect root must be '.' (the project dir itself)
        assert "jest/smoke" not in joined
