"""Probe spec must flag posix=False for Windows workers — the factory
selects sh vs powershell/cmd steps from it, so a missing flag silently
runs `sh -c` on Windows and the probe can never produce markers."""
import json

from testorchestrator import runner_readiness
from testorchestrator.extensions import db
from testorchestrator.execution import Runner, RuntimeConnection


class _StubAdapter:
    captured = None

    def submit(self, builder_name, execution_id, properties=None):
        _StubAdapter.captured = (builder_name, execution_id, properties)
        return 4242


def _mk(app, os_arch):
    with app.app_context():
        r = Runner(name="w", os_arch=os_arch, connection_mode="remote",
                   target_type="buildbot-worker", enabled=True)
        db.session.add(r)
        db.session.flush()
        rt = RuntimeConnection(
            name="rt", runner_id=r.id, transport="buildbot-worker",
            executable_path="C:\\Python312\\python.exe",
            runtime_kind="jest")
        db.session.add(rt)
        db.session.commit()
        return rt.id


def _submit(app, monkeypatch, tmp_path, os_arch):
    from testorchestrator import buildbot_cfg
    rtid = _mk(app, os_arch)
    monkeypatch.setattr(buildbot_cfg, "stage_probe_source",
                        lambda rid, scripts: None)
    monkeypatch.setattr(buildbot_cfg, "builder_for",
                        lambda runner: "b1")
    monkeypatch.setattr(buildbot_cfg, "staging_dir", lambda: tmp_path)
    monkeypatch.setattr(runner_readiness.BuildbotAdapter,
                        "from_settings", classmethod(lambda cls:
                                                     _StubAdapter()))
    with app.app_context():
        rt = db.session.get(RuntimeConnection, rtid)
        ok, msg = runner_readiness.submit(rt)
        assert ok, msg
    _, _, props = _StubAdapter.captured
    return json.loads(props["exec_spec"])


def test_probe_spec_posix_linux(app, monkeypatch, tmp_path):
    spec = _submit(app, monkeypatch, tmp_path, "linux-x86_64")
    assert spec["posix"] is True
    assert spec["executable"] == "sh"


def test_probe_spec_posix_windows(app, monkeypatch, tmp_path):
    spec = _submit(app, monkeypatch, tmp_path, "windows-x86_64")
    assert spec["posix"] is False
    assert spec["executable"] == "cmd"


def test_worker_loop_processes_probe_completions(app, monkeypatch):
    """Unattended installs must not depend on a UI render to advance
    probe completion — the worker maintenance loop calls
    poll_all_pending itself (D-PROBE-UI-RENDER)."""
    from testorchestrator import dispatch
    calls = []
    monkeypatch.setattr(runner_readiness, "poll_all_pending",
                        lambda: calls.append(1) or 0)
    with app.app_context():
        dispatch.worker_once()
    assert calls, "worker_once never polled probe completions"
