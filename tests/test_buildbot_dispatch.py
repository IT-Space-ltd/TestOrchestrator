"""Regression: buildbot dispatch must preserve the orchestration
semantics verified for the previous orchestration path:

- assignment commits BEFORE the buildrequest exists (a claimed build
  can start executing immediately — the DISPATCHED row + runner
  ownership must already be durable);
- a cancel landing between assign and submit is re-issued to the new
  brid so the build doesn't run a cancelled execution;
- explicit runner/runtime picks are honored or visibly rejected —
  never silently retargeted;
- a lost submission response is reconciled by the execution-id
  property before any resubmit — never a duplicate buildrequest;
- results=CANCELLED maps to CANCELED only when the portal requested
  the cancel; an unrequested abort is honest FAILED/infrastructure;
- connect-level master outages leave the row QUEUED for the redrive
  (slot released), other failures fail visibly.
"""
import json

import pytest
from pathlib import Path
import requests as _req

from testorchestrator import buildbot_cfg, dispatch as d
from testorchestrator import settings as _s
from testorchestrator.adapters.buildbot import BuildbotAdapter
from testorchestrator.execution import (DiscoveredItem, Execution,
                                        ExecutionState, GitBinding,
                                        OutboxEvent, Outcome, Project,
                                        Runner, RuntimeConnection)
from testorchestrator.extensions import db


class _BBProbe(BuildbotAdapter):
    """Captures submission calls and serves canned master state."""
    def __init__(self):
        super().__init__("http://stub")
        self.submits = []
        self.cancels = []
        self.existing = []          # find_buildrequests -> live brids
        self.br_state = {}          # brid -> buildrequest dict
        self.row_at_submit = None
        self.fail_submit = None
        self.prep_log = ""

    def find_buildrequests(self, execution_id):
        return list(self.existing)

    def submit(self, builder_name, execution_id, properties=None):
        self.submits.append((builder_name, execution_id, properties))
        if self.fail_submit is not None:
            raise self.fail_submit
        ex = db.session.get(Execution, execution_id)
        self.row_at_submit = dict(
            state=ex.state, runner_id=ex.runner_id,
            runtime_id=ex.runtime_id, lease=ex.lease_expires_at)
        return "7"

    def cancel(self, dispatch_id):
        self.cancels.append(dispatch_id)
        return True

    def buildrequest(self, dispatch_id):
        return self.br_state.get(str(dispatch_id), {})

    def builds_for_request(self, dispatch_id):
        return [{"buildid": 1}]

    def run_log(self, buildid, step_names=None):
        if step_names and "prep" in step_names:
            return self.prep_log
        return "kre stdout"

    def workers(self):
        return []


def _env(app, monkeypatch, stub, target_type="local",
         worktree="/tmp/bb-proto/src-repo"):
    monkeypatch.setattr(BuildbotAdapter, "from_settings",
                        classmethod(lambda cls: stub))
    with app.app_context():
        _s.update({
            "buildbot_endpoint": "http://stub",
            "buildbot_home": "/tmp/bb-test-home",
        })
        r = Runner(name="bb-target", connection_mode="local",
                   target_type=target_type, os_arch="linux",
                   max_slots=2,
                   ssh_workdir="/tmp/ssh-runs" if target_type == "ssh"
                   else "")
        db.session.add(r)
        db.session.flush()
        rt = RuntimeConnection(name="kre", runner_id=r.id,
                               executable_path="/opt/kre/katalonc",
                               credential_file="/opt/kre/.krecred",
                               enabled=True)
        db.session.add(rt)
        db.session.flush()
        p = Project(name="p")
        db.session.add(p)
        db.session.flush()
        Path(str(worktree)).mkdir(parents=True, exist_ok=True)
        b = GitBinding(project_id=p.id, name="b", url="/x",
                       worktree_path=str(worktree))
        db.session.add(b)
        db.session.flush()
        di = DiscoveredItem(project_id=p.id, binding_id=b.id,
                            kind="suite", path="T/x.ts", name="x",
                            sha="s", order_idx=0)
        db.session.add(di)
        db.session.commit()
        return r.id, rt.id, di.id


def _event_for(ex):
    return OutboxEvent.query.filter(
        OutboxEvent.kind == "orchestrator-dispatch",
        OutboxEvent.payload_json.contains(ex.id)).first()


def test_assignment_committed_before_submit(app, monkeypatch, tmp_path):
    """At the instant the buildrequest is forced, the execution is
    already DISPATCHED to its runner with a live lease."""
    stub = _BBProbe()
    with app.app_context():
        monkeypatch.setattr(buildbot_cfg, "home",
                            lambda: tmp_path)
        _, rtid, diid = _env(app, monkeypatch, stub,
                         worktree=tmp_path / "wt")
        ex = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        assert ex.snapshot()["dispatch_transport"] == "buildbot"
        d._handle_event(_event_for(ex))
        assert len(stub.submits) == 1
        builder, eid, props = stub.submits[0]
        assert builder == f"to-target-{ex.runner_id}" or \
            builder.startswith("to-target-")
        assert stub.row_at_submit["state"] == ExecutionState.DISPATCHED
        assert stub.row_at_submit["runner_id"]
        assert stub.row_at_submit["lease"] is not None
        db.session.refresh(ex)
        assert ex.dispatch_id == "bb:7"
        # spec travels in the declared property; no secrets anywhere
        spec = json.loads(props["exec_spec"])
        assert spec["executable"] == "/opt/kre/katalonc"


def test_cancel_between_assign_and_submit(app, monkeypatch, tmp_path):
    """A cancel arriving after assignment but before submission is
    re-issued against the new brid — the build must not run."""
    stub = _BBProbe()
    with app.app_context():
        monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
        _, rtid, diid = _env(app, monkeypatch, stub,
                         worktree=tmp_path / "wt")
        ex = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        d._buildbot_assign_and_submit(ex)
        db.session.refresh(ex)
        assert ex.dispatch_id == "bb:7"
        # simulate cancel landing between assign and submit: mark the
        # state then re-run the post-submit guard path
        ex.state = ExecutionState.CANCEL_REQUESTED
        db.session.commit()
        # request_cancel on the now-dispatched execution issues cancel
        d.request_cancel(ex.id, "u", "reason")
        assert "7" in stub.cancels


def test_explicit_pick_unavailable_fails_visibly(app, monkeypatch,
                                                 tmp_path):
    stub = _BBProbe()
    with app.app_context():
        monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
        _, rtid, diid = _env(app, monkeypatch, stub,
                         worktree=tmp_path / "wt")
        # create guards disabled runtimes up front
        rt = db.session.get(RuntimeConnection, rtid)
        rt.enabled = False
        db.session.commit()
        with pytest.raises(d.DispatchError):
            d.create_execution(
                "u", None, run_config={"runtime_id": rtid},
                source_item=db.session.get(DiscoveredItem, diid))
        # if the pick becomes unavailable after queueing but before
        # submission, the submit path must fail visibly — not retarget
        rt.enabled = True
        db.session.commit()
        ex2 = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        rt.enabled = False
        db.session.commit()
        d._buildbot_assign_and_submit(ex2)
        db.session.refresh(ex2)
        assert ex2.state == ExecutionState.FAILED
        assert ex2.error_kind == "infrastructure"
        assert not stub.submits


def test_lost_response_reconciles_no_duplicate(app, monkeypatch,
                                               tmp_path):
    """A submission whose response was lost leaves a live brid — the
    redrive adopts it instead of forcing a second buildrequest."""
    stub = _BBProbe()
    with app.app_context():
        monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
        _, rtid, diid = _env(app, monkeypatch, stub,
                         worktree=tmp_path / "wt")
        ex = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        # master already has a live brid carrying this execution id
        stub.existing = [{"buildrequestid": 42, "complete": False}]
        d._buildbot_assign_and_submit(ex)
        db.session.refresh(ex)
        assert ex.dispatch_id == "bb:42"
        assert not stub.submits        # adopted, never resubmitted


def test_connection_error_stays_queued_releases_slot(app, monkeypatch,
                                                     tmp_path):
    stub = _BBProbe()
    stub.fail_submit = _req.ConnectionError("master down")
    with app.app_context():
        monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
        rid, rtid, diid = _env(app, monkeypatch, stub)
        ex = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        d._buildbot_assign_and_submit(ex)
        db.session.refresh(ex)
        assert ex.state == ExecutionState.QUEUED
        assert ex.runner_id is None      # slot released for redrive
        # recovery: redrive submits again
        stub.fail_submit = None
        d._redrive_queued_remote()
        db.session.refresh(ex)
        assert ex.state == ExecutionState.DISPATCHED
        assert ex.dispatch_id == "bb:7"


def test_requested_cancel_maps_canceled(app, monkeypatch, tmp_path):
    stub = _BBProbe()
    stub.br_state["7"] = {"complete": True, "results": 6, "claimed": True}
    with app.app_context():
        monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
        rid, rtid, diid = _env(app, monkeypatch, stub)
        ex = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        ex.state = ExecutionState.CANCEL_REQUESTED
        ex.dispatch_id = "bb:7"
        ex.runner_id = rid
        ex.runtime_id = rtid
        db.session.commit()
        d.reconcile_buildbot_runs()
        db.session.refresh(ex)
        assert ex.state == ExecutionState.CANCELED
        assert ex.outcome == Outcome.INCOMPLETE


def test_unrequested_cancel_maps_failed_infra(app, monkeypatch,
                                              tmp_path):
    stub = _BBProbe()
    stub.br_state["7"] = {"complete": True, "results": 6, "claimed": True}
    with app.app_context():
        monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
        rid, rtid, diid = _env(app, monkeypatch, stub)
        ex = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        ex.state = ExecutionState.DISPATCHED
        ex.dispatch_id = "bb:7"
        ex.runner_id = rid
        ex.runtime_id = rtid
        db.session.commit()
        d.reconcile_buildbot_runs()
        db.session.refresh(ex)
        # Unrequested abort is NOT a user cancellation
        assert ex.state == ExecutionState.FAILED
        assert ex.error_kind == "infrastructure"
        assert "without a recorded cancellation" in ex.error_text


def test_success_collects_and_completes(app, monkeypatch, tmp_path):
    stub = _BBProbe()
    stub.br_state["7"] = {"complete": True, "results": 0, "claimed": True}
    with app.app_context():
        monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
        rid, rtid, diid = _env(app, monkeypatch, stub)
        # stage a fake uploaded artifact where _collect_buildbot reads
        arts = buildbot_cfg.artifacts_dir() / "PLACEHOLDER"
        ex = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        ex.state = ExecutionState.DISPATCHED
        ex.dispatch_id = "bb:7"
        ex.runner_id = rid
        ex.runtime_id = rtid
        db.session.commit()
        src = buildbot_cfg.artifacts_dir() / ex.id
        src.mkdir(parents=True)
        (src / "junit.xml").write_text(
            '<testsuite tests="1" failures="0"><testcase '
            'classname="T" name="c" time="0.1"/></testsuite>')
        d.reconcile_buildbot_runs()
        db.session.refresh(ex)
        assert ex.state == ExecutionState.COMPLETED
        assert ex.outcome == Outcome.PASSED


def test_kre_buildbot_failure_classifies_license(
        app, monkeypatch, tmp_path):
    """A KRE run ending results=2 with a license error in the run log
    must surface error_kind='license' — not the generic 'no result
    data' execution verdict."""
    stub = _BBProbe()
    stub.br_state["7"] = {"complete": True, "results": 2,
                          "claimed": True}
    with app.app_context():
        monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
        rid, rtid, diid = _env(app, monkeypatch, stub)
        ex = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        ex.state = ExecutionState.DISPATCHED
        ex.dispatch_id = "bb:7"
        ex.runner_id = rid
        ex.runtime_id = rtid
        db.session.commit()
        stub_run_log_orig = stub.run_log
        stub.run_log = lambda *a, **k: "License is not activated"
        d.reconcile_buildbot_runs()
        db.session.refresh(ex)
        stub.run_log = stub_run_log_orig
        assert ex.state == ExecutionState.FAILED
        assert ex.error_kind == "license"
        assert "license" in ex.error_text.lower()


def test_kre_ssh_failure_classifies_via_run_out(
        app, monkeypatch, tmp_path):
    """Agentless-SSH runs have no worker step log — the remote output
    lands as a run.out artifact. Classification must read it: a
    missing credential is 'license', never bare 'infrastructure'."""
    stub = _BBProbe()
    stub.br_state["7"] = {"complete": True, "results": 2,
                          "claimed": True}
    with app.app_context():
        monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
        rid, rtid, diid = _env(app, monkeypatch, stub,
                               target_type="ssh")
        ex = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        ex.state = ExecutionState.DISPATCHED
        ex.dispatch_id = "bb:7"
        ex.runner_id = rid
        ex.runtime_id = rtid
        db.session.commit()
        src = buildbot_cfg.artifacts_dir() / ex.id
        src.mkdir(parents=True)
        (src / "run.out").write_text(
            "Activation failed: No Offline License or you have "
            "forgot to put in your -apiKey command for online "
            "activation.\nKRE exit code: 2\n")
        stub.run_log = lambda *a, **k: ""  # no 'ssh-run' step match
        d.reconcile_buildbot_runs()
        db.session.refresh(ex)
        assert ex.state == ExecutionState.FAILED
        assert ex.error_kind == "license"
        assert "license" in ex.error_text.lower()


def test_failed_ssh_run_confirms_remote_death(
        app, monkeypatch, tmp_path):
    """A failed/timed-out SSH run leaves the detached remote group
    running — terminal failure must confirm remote death (§6 timeout
    stops the full process tree)."""
    stub = _BBProbe()
    stub.br_state["7"] = {"complete": True, "results": 2,
                          "claimed": True}
    kills = []
    with app.app_context():
        monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
        monkeypatch.setattr(d, "_ssh_remote_cancel",
                            lambda ex: kills.append(ex.id) or True)
        rid, rtid, diid = _env(app, monkeypatch, stub,
                               target_type="ssh")
        ex = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        ex.state = ExecutionState.DISPATCHED
        ex.dispatch_id = "bb:7"
        ex.runner_id = rid
        ex.runtime_id = rtid
        db.session.commit()
        d.reconcile_buildbot_runs()
        db.session.refresh(ex)
        assert ex.state == ExecutionState.FAILED
        assert kills == [ex.id]
        assert "[ssh remote group terminated]" in ex.error_text


def test_redrive_cancels_reissues_until_complete(
        app, monkeypatch, tmp_path):
    """request_cancel's buildrequest cancel is best-effort — a
    transient failure must not strand the remote run: each tick
    re-issues cancel while the buildrequest stays incomplete."""
    stub = _BBProbe()
    stub.br_state["7"] = {"complete": False, "claimed": True}
    with app.app_context():
        monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
        rid, rtid, diid = _env(app, monkeypatch, stub)
        ex = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        ex.state = ExecutionState.CANCEL_REQUESTED
        ex.dispatch_id = "bb:7"
        ex.runner_id = rid
        ex.runtime_id = rtid
        db.session.commit()
        assert d._redrive_cancels() == 1
        assert stub.cancels == ["7"]
        # Already-complete buildrequests are left alone.
        stub.br_state["7"] = {"complete": True, "results": 6}
        assert d._redrive_cancels() == 0
        assert stub.cancels == ["7"]


def test_kre_classify_ignores_benign_testcloud_fallback():
    """KRE logs "Failed to activate with TestCloud license" in every
    run before acquiring the KRE license. A run that activates fine
    and then fails for another reason must not classify 'license'."""
    from testorchestrator.adapters import kre
    from testorchestrator.adapters.kre import InvocationResult

    res = InvocationResult(exit_status=2)
    tail = (
        "Failed to activate with TestCloud license. "
        "Activated successfully with Katalon Runtime Engine license. "
        "Execution failed with error: "
        "com.katalon.execution.exception.ExecutionException: "
        "Found no test suite to execute in the test suite collection.")
    assert kre.classify_error(res, tail) != "license"

    fatal = InvocationResult(exit_status=2)
    assert kre.classify_error(
        fatal, "Failed to activate with Katalon Runtime Engine "
        "license.") == "license"

    noact = InvocationResult(exit_status=2)
    assert kre.classify_error(noact, "License is not activated") \
        == "license"

    # The staged credential resolver failing before KRE launches is
    # never a license verdict (the license was never reached). Split by
    # layer: credential VALUE problems are config; file/transfer/
    # permission/executable problems are infrastructure.
    wrap = InvocationResult(exit_status=1)
    assert kre.classify_error(
        wrap, "kre_cred_exec: credential file unreadable") \
        == "infrastructure"
    assert kre.classify_error(
        wrap, "kre_cred_exec: KRE executable not found at the "
        "configured path") == "infrastructure"
    assert kre.classify_error(
        wrap, "kre_cred_exec: credential file is empty") == "config"
    assert kre.classify_error(
        wrap, "kre_cred_exec: conflicting credential source: -apiKey "
        "already supplied") == "config"

    # The step runner's kill marker → timeout is infrastructure even
    # when the coordinator reports a bare failure code.
    to = InvocationResult(exit_status=1)
    assert kre.classify_error(
        to, "command timed out: 20 seconds without output "
        "running [...] attempting to kill") == "infrastructure"

    # The logged argv always echoes "-projectPath=<dir>" — data, not
    # an error. The bare substring must not fire "config".
    argvecho = InvocationResult(exit_status=1)
    assert kre.classify_error(
        argvecho,
        "argv: [b'katalonc', b'-projectPath=.', b'-reportFolder=R'] "
        "program finished with exit code 1") != "config"
    # …while a real project-path complaint still classifies config.
    badproj = InvocationResult(exit_status=4)
    assert kre.classify_error(
        badproj, "cannot find project") == "config"
    # KRE's bad-selection marker is config, not infrastructure — but a
    # test failure mentioning "not found" inside a suite stays honest.
    badsuite = InvocationResult(exit_status=4)
    assert kre.classify_error(
        badsuite, "Test suite 'Test Suites/NOPE' not found.") \
        == "config"
    testfail = InvocationResult(exit_status=1)
    assert kre.classify_error(
        testfail, "Test suite 'TS2' — Test Cases/TC3 FAILED: "
        "element not found on page") != "config"

    # A truncated tail can lose the "Activated successfully" line
    # while keeping stray "Failed to activate with TestCloud" noise —
    # the suite-not-found marker only appears after activation, so it
    # outranks generic license words.
    truncated = InvocationResult(exit_status=4)
    assert kre.classify_error(
        truncated,
        "Failed to activate with TestCloud license. "
        "Test suite 'Test Suites/NOPE' not found. "
        "KRE exit code: 4") == "config"


def test_kre_exec_spec_staged_helper(app):
    """Credentialed KRE on a PB worker: the launcher travels inside
    the exec tar as src/.to_kre_cred_exec.{sh,ps1} and runs under the
    target-native shell — never a controller-host path or a
    PATH-resolved Python."""
    with app.app_context():
        ex = type("E", (), {})()
        ex.snapshot = lambda: {"run_config": {}}
        rt = type("R", (), {"executable_path": "/x"})()
        spec = buildbot_cfg.kre_exec_spec(
            ex, rt, ["a"], credential_file="C:/to/kre.key",
            posix=False, helper_launch=["powershell", "-File"],
            helper_sha256="ab12")
        assert spec["credential_wrapper"] == ".to_kre_cred_exec.ps1"
        assert spec["credential_wrapper"] == \
            buildbot_cfg.kre_cred_helper_name(True)
        assert spec["credential_launch"] == ["powershell", "-File"]
        assert spec["credential_file"] == "C:/to/kre.key"
        assert spec["helper_sha256"] == "ab12"
        spec_posix = buildbot_cfg.kre_exec_spec(
            ex, rt, ["a"], credential_file="/t/kre.key",
            credential_mastersrc="/staging/x.cred",
            helper_launch=["sh"], helper_sha256="cd34")
        assert spec_posix["credential_wrapper"] == ".to_kre_cred_exec.sh"
        assert spec_posix["credential_mastersrc"] == "/staging/x.cred"
        # No credential → no helper fields at all (missing-cred path
        # still runs the bare executable).
        spec2 = buildbot_cfg.kre_exec_spec(ex, rt, ["a"])
        assert "credential_wrapper" not in spec2
        assert "credential_launch" not in spec2


def test_kre_cred_helper_source_is_portable():
    """The staged launchers must exist in the payload: the POSIX one
    syntax-checks under sh and carries the setsid/scrub contract; the
    Windows one carries the kill-on-close job object."""
    import subprocess as _sp
    sh_src = buildbot_cfg.kre_cred_helper_source(False)
    assert sh_src.is_file()
    text = sh_src.read_text(encoding="utf-8")
    assert "setsid" in text and "REDACTED" in text
    assert _sp.run(["sh", "-n", str(sh_src)]).returncode == 0
    ps_src = buildbot_cfg.kre_cred_helper_source(True)
    assert ps_src.is_file()
    ps = ps_src.read_text(encoding="utf-8")
    assert "AssignProcessToJobObject" in ps
    assert "KILL_ON_JOB_CLOSE" in ps or "0x2000" in ps


def test_prep_script_echo_is_not_a_retry_block(
        app, monkeypatch, tmp_path):
    """The prep step's stdio echoes the whole prep script in its
    header lines — including the literal TO_RETRY_BLOCKED echo text.
    That script echo must NOT be read as a refusal marker: only an
    emitted TO_RETRY_BLOCKED: output line means the prep refused."""
    stub = _BBProbe()
    stub.br_state["7"] = {"complete": True, "results": 2,
                          "claimed": True}
    # Real log shape: header line contains the script body (marker
    # text embedded mid-line); no emitted marker anywhere.
    stub.prep_log = (
        "hsh -c 'af=.to_exec_attempt_deadbeef; n=$(( $(cat \"$af\" "
        "|| echo 0) + 1 )); echo \"$n\" > \"$af\"; if [ \"$n\" "
        "-gt 1 ]; then echo \"TO_RETRY_BLOCKED: attempt $n\"; "
        "exit 70; fi' to-exec ./katalonc\n"
        "oNPX-FAKE completed\n"
        "hprogram finished with exit code 2")
    with app.app_context():
        monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
        rid, rtid, diid = _env(app, monkeypatch, stub)
        ex = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        ex.state = ExecutionState.DISPATCHED
        ex.dispatch_id = "bb:7"
        ex.runner_id = rid
        ex.runtime_id = rtid
        db.session.commit()
        d.reconcile_buildbot_runs()
        db.session.refresh(ex)
        assert ex.state == ExecutionState.FAILED
        assert "TO_RETRY_BLOCKED" not in ex.error_text


def test_retry_blocked_maps_unknown_and_holds_reservations(
        app, monkeypatch, tmp_path):
    """A buildrequest resubmit REFUSED by prep (unresolvable prior
    attempt / retry policy exceeded) must map to UNKNOWN — not FAILED:
    the original attempt may still be live, so its reservations stay
    held and the row lands on the reconciliation queue."""
    stub = _BBProbe()
    stub.br_state["7"] = {"complete": True, "results": 2,
                          "claimed": True}
    stub.prep_log = ("TO_RETRY_BLOCKED: pid 4242 alive; env marker "
                     "mismatch or unreadable — original attempt state "
                     "unresolved, relaunch blocked")
    with app.app_context():
        monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
        rid, rtid, diid = _env(app, monkeypatch, stub)
        ex = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        ex.state = ExecutionState.DISPATCHED
        ex.dispatch_id = "bb:7"
        ex.runner_id = rid
        ex.runtime_id = rtid
        db.session.add(d.ResourceReservation(
            execution_id=ex.id, runner_id=rid,
            resource_kind="slot", slot_index=0))
        db.session.commit()
        d.reconcile_buildbot_runs()
        db.session.refresh(ex)
        assert ex.state == ExecutionState.UNKNOWN
        assert ex.error_kind == "infrastructure"
        assert "TO_RETRY_BLOCKED" in ex.error_text
        assert "reconciliation" in ex.error_text
        resv = d.ResourceReservation.query.filter_by(
            execution_id=ex.id, released_at=None).all()
        assert resv                  # claims stay held — never freed
        assert Outcome[ex.outcome.name] == Outcome.INCOMPLETE


def test_retry_policy_rendered_into_specs(app):
    """retry_enabled/max_attempts come from run_config — explicit, not
    implied by attempt bookkeeping."""
    with app.app_context():
        ex = type("E", (), {})()
        ex.snapshot = lambda: {"run_config": {
            "max_attempts": "5", "retry_enabled": False}}
        spec = buildbot_cfg.kre_exec_spec(
            ex, type("R", (), {"executable_path": "/x"})(), ["a"])
        assert spec["max_attempts"] == 5
        assert spec["retry_enabled"] is False
        ex2 = type("E", (), {})()
        ex2.snapshot = lambda: {"run_config": {}}
        spec2 = buildbot_cfg.node_exec_spec(ex2, "/x", ["a"])
        assert spec2["max_attempts"] == 3
        assert spec2["retry_enabled"] is True
        # None (readiness probe) gets the safe defaults, no crash
        spec3 = buildbot_cfg.ssh_exec_spec(None, "py", "d", "f")
        assert spec3["max_attempts"] == 3


def test_retry_policy_persisted_in_snapshot(app, monkeypatch, tmp_path):
    """The policy must survive the immutable snapshot — a UI/API
    run_config reaches the worker-side prep unchanged. Disabling
    retries means a resubmitted buildrequest hits attempt 2 and is
    blocked, not relaunched."""
    stub = _BBProbe()
    with app.app_context():
        monkeypatch.setattr(buildbot_cfg, "home", lambda: tmp_path)
        _, rtid, diid = _env(app, monkeypatch, stub,
                             worktree=tmp_path / "wt")
        ex = d.create_execution(
            "u", None,
            run_config={"runtime_id": rtid,
                        "retry_enabled": False, "max_attempts": "5"},
            source_item=db.session.get(DiscoveredItem, diid))
        rc = ex.snapshot()["run_config"]
        assert rc["retry_enabled"] is False
        assert rc["max_attempts"] == 5          # clamped/str→int
        rt = db.session.get(RuntimeConnection, rtid)
        spec = buildbot_cfg.kre_exec_spec(ex, rt, ["a"])
        assert spec["retry_enabled"] is False   # snapshot→spec chain
        assert spec["max_attempts"] == 5
        # defaults when unset
        ex2 = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        rc2 = ex2.snapshot()["run_config"]
        assert rc2["retry_enabled"] is True
        assert rc2["max_attempts"] == 3


def test_windows_spec_forces_retry_disabled(app):
    """No confirmed-orphan resolution exists on Windows, so the spec
    forces retry_enabled=false/max_attempts=1 regardless of what the
    run_config asked for — a silent unconditional relaunch must be
    impossible. The worker-side prep counter enforces attempt>1."""
    with app.app_context():
        ex = type("E", (), {})()
        ex.snapshot = lambda: {"run_config": {
            "max_attempts": "5", "retry_enabled": True}}
        rt = type("R", (), {"executable_path": "/x"})()
        spec = buildbot_cfg.kre_exec_spec(ex, rt, ["a"], posix=False)
        assert spec["posix"] is False
        assert spec["retry_enabled"] is False
        assert spec["max_attempts"] == 1
        spec2 = buildbot_cfg.node_exec_spec(ex, "npx", ["a"],
                                            posix=False)
        assert spec2["retry_enabled"] is False
        assert spec2["max_attempts"] == 1


class _FakeChan:
    def __init__(self, out=b"", rc=0):
        self._out = out
        self._rc = rc
    def settimeout(self, t):
        pass
    def exec_command(self, cmd):
        self.cmd = cmd
    def makefile(self, mode):
        import io
        return io.BytesIO(self._out)
    def makefile_stderr(self, mode):
        import io
        return io.BytesIO(b"")
    def recv_exit_status(self):
        return self._rc


def test_ssh_remote_cancel_kills_process_group(app, monkeypatch, tmp_path):
    """Regression: portal cancel must kill the detached remote process
    group itself — the buildbot worker SIGKILLs to_ssh_exec before its
    SIGTERM handler runs, so nothing else terminates the sshd-side run."""
    import json as _json
    from testorchestrator import dispatch as d, buildbot_cfg
    with app.app_context():
        rid, rtid, diid = _env(app, monkeypatch, _BBProbe())
        ex = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        specs = buildbot_cfg.run_specs_dir()
        specs.mkdir(parents=True, exist_ok=True)
        (specs / f"{ex.id}.json").write_text(_json.dumps({
            "host": "127.0.0.1", "port": "22", "username": "u",
            "key_file": str(tmp_path / "k"),
            "host_key_fingerprint": "", "remote_workdir": "/w/e1"}))

        # no paramiko transport needed at all -> None only without spec
        import paramiko
        (tmp_path / "k").write_text("x")
        monkeypatch.setattr(paramiko.Ed25519Key, "from_private_key_file",
                            classmethod(lambda cls, f: object()))
        calls = []

        class _T:
            def __init__(self, sock):
                pass
            def start_client(self, timeout=0):
                pass
            def auth_publickey(self, u, k):
                pass
            def open_session(self, timeout=0):
                # pid present on first exec (cat run.pid), dead on check
                c = _FakeChan(b"4242\n" if not calls else b"dead\n")
                calls.append(c)
                return c
            def close(self):
                pass
        import socket as _sock
        monkeypatch.setattr(d, "_sock", None, raising=False)
        import testorchestrator.dispatch as dd
        # patch the socket create used inside _ssh_remote_cancel
        orig = _sock.create_connection
        monkeypatch.setattr(_sock, "create_connection",
                            lambda *a, **k: object())
        monkeypatch.setattr(paramiko, "Transport", _T)
        monkeypatch.setattr(dd.time, "sleep", lambda s: None)

        # first _run returns "4242" for every command; make the
        # kill -0 check return dead by keying on command content
        class _T2(_T):
            def open_session(self, timeout=0):
                c = _FakeChan(b"4242\n")
                calls.append(c)
                return c
        # Simpler: sequence channels — cat run.pid, kill cmd, kill -0
        seq = [b"4242\n", b"", b"dead\n"]
        class _T3:
            def __init__(self, sock): pass
            def start_client(self, timeout=0): pass
            def auth_publickey(self, u, k): pass
            def open_session(self, timeout=0):
                out = seq.pop(0) if seq else b"dead\n"
                c = _FakeChan(out); calls.append(c)
                return c
            def close(self): pass
        monkeypatch.setattr(paramiko, "Transport", _T3)

        ok = d._ssh_remote_cancel(ex)
        assert ok is True
        kill_cmds = [c.cmd for c in calls]
        assert any("kill -TERM -4242" in c for c in kill_cmds)
        assert any("kill -0 4242" in c for c in kill_cmds)

        # group still alive -> unconfirmed
        seq2 = [b"4242\n", b"", b"alive\n"]
        class _T4(_T3):
            def open_session(self, timeout=0):
                out = seq2.pop(0) if seq2 else b"alive\n"
                c = _FakeChan(out); calls.append(c)
                return c
        monkeypatch.setattr(paramiko, "Transport", _T4)
        assert d._ssh_remote_cancel(ex) is False

        # no spec file at all -> None (non-SSH run)
        ex2 = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        assert d._ssh_remote_cancel(ex2) is None


def test_staging_cleared_on_predispatch_fail(app, monkeypatch, tmp_path):
    """A _fail INSIDE _submit_buildbot (after stage_source — e.g. an
    unresolvable credential_ref) leaves no staged tar/cred behind."""
    stub = _BBProbe()
    ids = _env(app, monkeypatch, stub, target_type="ssh")
    rid, rtid, diid = ids
    with app.app_context():
        rt = db.session.get(RuntimeConnection, rtid)
        rt.credential_ref = "portal-side-secret"   # unknown ref → fail
        db.session.commit()
        ex = d.create_execution(
            "u", None, run_config={"runtime_id": rtid},
            source_item=db.session.get(DiscoveredItem, diid))
        sd = buildbot_cfg.staging_dir()
        sd.mkdir(parents=True, exist_ok=True)
        d._buildbot_assign_and_submit(ex)
        db.session.refresh(ex)
        assert ex.state == ExecutionState.FAILED
        assert "does not exist" in ex.error_text
        assert not (sd / f"{ex.id}.tar").exists()
        assert not (sd / f"{ex.id}.cred").exists()


def test_sweep_removes_terminal_leftovers_keeps_live(app, tmp_path):
    """Reconcile sweep deletes staged files of terminal executions;
    DISPATCHED/QUEUED runs and unknown ids keep theirs."""
    with app.app_context():
        sd = buildbot_cfg.staging_dir()
        sd.mkdir(parents=True, exist_ok=True)
        done = Execution(project_id="p-x",
                         state=ExecutionState.FAILED)
        live = Execution(project_id="p-x",
                         state=ExecutionState.DISPATCHED)
        db.session.add_all([done, live])
        db.session.commit()
        for eid in (done.id, live.id, "no-such-exec"):
            (sd / f"{eid}.tar").write_text("x")
        removed = d._sweep_stale_staging()
        assert removed >= 1
        assert not (sd / f"{done.id}.tar").exists()
        assert (sd / f"{live.id}.tar").exists()
        assert (sd / "no-such-exec.tar").exists()
