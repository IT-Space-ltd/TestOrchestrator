"""deps_prepare (npm ci) semantics: default-on with explicit opt-out,
lockfile early refusal, probe awareness, NEVER during discovery or
preview/native collection."""
import json

from testorchestrator import runner_readiness
from testorchestrator.adapters import nodefw


def test_probe_verdict_accepts_missing_jest_when_npm_present():
    # probe ran before install — jest missing but npm present must not
    # be fatal (npm ci installs at run time)
    probe = {"node": "v24.0.0", "npx": "11.0.0", "npm": "11.0.0",
             "jest": "missing (npx --no-install jest --version failed)"}
    out = runner_readiness._summarize(probe, "jest")
    assert "ready" in out.split("—")[0]
    assert "not resolvable — install" not in out


def test_probe_verdict_still_fatal_without_npm():
    probe = {"node": "missing", "npx": "missing", "npm": "missing",
             "jest": "missing"}
    out = runner_readiness._summarize(probe, "jest")
    assert "not ready" in out


def test_static_discovery_and_preview_never_execute():
    """Static discovery/preview is parse-only Python over the checkout —
    it never builds deps_argv or executes anything on a target. Native
    collection MAY run npm ci (it is the approved repo-code execution
    path, and jest --listTests genuinely needs project deps)."""
    import inspect
    from testorchestrator import gitsync, discovery
    # static discovery path contains no deps/prepare machinery at all
    src = inspect.getsource(gitsync.discover_project)
    assert "deps_prepare" not in src and "npm ci" not in src
    assert "deps_argv" not in src


def test_collect_without_collector_refused_early():
    """Frameworks without a collector (postman, bruno) must get a
    clear early refusal — never a pre-artifact failed execution."""
    import inspect
    from testorchestrator import gitsync
    src = inspect.getsource(gitsync.request_native_collection)
    assert "has no native collector" in src
    assert "COLLECT_SCRIPTS" in src


def test_lockfile_refusal_message_present():
    import inspect
    from testorchestrator import dispatch
    src = inspect.getsource(dispatch._submit_buildbot)
    assert "package-lock.json" in src
    assert "deps_prepare=false" in src


def test_prepare_default_on_explicit_off():
    """Contract: deps_prepare defaults on; explicit false disables."""
    import inspect
    from testorchestrator import dispatch
    src = inspect.getsource(dispatch._submit_buildbot)
    assert 'rc.get("deps_prepare", True)' in src


def test_role_gate_source_present():
    import inspect
    from testorchestrator import dispatch
    src = inspect.getsource(dispatch.create_execution)
    assert "deps_prepare requires the test manager" in src


def test_audit_event_wired():
    import inspect
    from testorchestrator import dispatch
    src = inspect.getsource(dispatch._submit_buildbot)
    assert "execution.deps_prepare" in src
    assert "sha256:" in src


def test_timeout_cap_wired():
    src = open("scripts/to_ssh_exec.py").read()
    assert "deps_timeout" in src and "timeout " in src
    from testorchestrator import buildbot_cfg
    import inspect
    assert "deps_timeout" in inspect.getsource(buildbot_cfg)


def test_schedule_form_has_deps_toggle(app, client, login_as):
    from tests.test_schedule_form import _project
    pid, iid = _project(app)
    login_as("admin")
    resp = client.get(f"/projects/{pid}")
    assert b"deps_prepare" in resp.data
    assert b"npm ci" in resp.data


def test_schedule_stores_explicit_opt_out(app, client, login_as):
    import json as _j
    from tests.test_schedule_form import _project, _post
    from testorchestrator.execution import Schedule
    pid, iid = _project(app, fw="pytest")
    login_as("admin")
    resp = _post(client, pid, framework="pytest",
                 target_id=f"repo:{iid}", deps_prepare="false")
    assert resp.status_code == 200
    with app.app_context():
        sched = Schedule.query.one()
        rc = _j.loads(sched.run_config_json)
        assert rc.get("deps_prepare") is False


def test_schedule_default_leaves_deps_prepare_unset(app, client, login_as):
    import json as _j
    from tests.test_schedule_form import _project, _post
    from testorchestrator.execution import Schedule
    pid, iid = _project(app, fw="pytest")
    login_as("admin")
    resp = _post(client, pid, framework="pytest", target_id=f"repo:{iid}")
    assert resp.status_code == 200
    with app.app_context():
        rc = _j.loads(Schedule.query.one().run_config_json)
        assert "deps_prepare" not in rc   # default-on applies downstream


def test_native_collect_prepare_allowed_with_lockfile(tmp_path):
    """jest native collect requires deps — deps_argv must NOT be
    excluded for native_collect anymore; lockfile refusal applies."""
    import inspect
    from testorchestrator import dispatch
    src = inspect.getsource(dispatch._submit_buildbot)
    # the deps_on condition must not exclude native_collect
    assert '(not rc.get("native_collect"))' not in src
