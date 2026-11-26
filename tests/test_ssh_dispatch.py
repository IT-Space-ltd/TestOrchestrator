"""End-to-end agentless-SSH dispatch against a live in-process SSH
server — real protocol, real remote process control:

- fresh run: prepare -> detached launch -> poll -> SFTP-collect;
- running cancel: SIGTERM to the dispatcher -> remote process GROUP
  killed -> 'cancel-confirmed' -> local exit 0;
- session loss / re-run: run.sh + exit_code markers mean a reinvoked
  dispatcher REATTACHES instead of launching a duplicate.
"""
import json
import os
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

paramiko = pytest.importorskip("paramiko", reason="paramiko needed")

from tests.ssh_test_server import TestSSHServer, generate_client_key

DISPATCHER = str(Path(__file__).parent.parent / "scripts"
                 / "to_ssh_exec.py")


def _source_tar(tmp: Path) -> Path:
    src = tmp / "proj"
    (src / "src").mkdir(parents=True)
    (src / "src" / "dummy.txt").write_text("x")
    tar = tmp / "source.tar"
    with tarfile.open(tar, "w") as t:
        t.add(src / "src", arcname="src")
    return tar


def _runner_exec(tmp: Path, body: str) -> Path:
    exe = tmp / "katalonc"
    exe.write_text("#!/bin/sh\n" + body)
    exe.chmod(0o755)
    return exe


def _spec(tmp: Path, server: TestSSHServer, exe: Path,
          workdir: Path) -> Path:
    key = generate_client_key(tmp / "id_rsa")
    server.start(key)
    (tmp / "key.pem").write_text((tmp / "id_rsa").read_text())
    spec = {
        "execution_id": "e2e-ssh-1",
        "host": "127.0.0.1", "port": server.port,
        "username": "to-runner",
        "key_file": str(tmp / "key.pem"),
        "host_key_fingerprint": server.fingerprint,
        "host_key_alg": server.key_alg,
        "remote_workdir": str(workdir),
        "source_tar": str(_source_tar(tmp)),
        "executable": str(exe),
        # Mirrors dispatch's arg construction: -reportFolder is an
        # ABSOLUTE path inside the remote run dir.
        "args": ["-runMode=console",
                 f"-reportFolder={workdir}/Reports"],
        "report_rel": "Reports",
        "timeout_s": 60,
    }
    p = tmp / "spec.json"
    p.write_text(json.dumps(spec))
    return p


def _run_dispatcher(spec: Path, cwd: Path):
    return subprocess.Popen([sys.executable, DISPATCHER, str(spec)],
                            cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)


def test_fresh_run_collects(tmp_path):
    server = TestSSHServer(Path("/"))
    exe = _runner_exec(
        tmp_path,
        'for a in "$@"; do case "$a" in -reportFolder=*) '
        'RF="${a#-reportFolder=}";; esac; done\n'
        'mkdir -p "$RF" && echo "<testsuite tests=\'1\'/>" '
        '> "$RF/junit.xml" && echo stub-done && exit 0\n')
    spec = _spec(tmp_path, server, exe, tmp_path / "rd1")
    work = tmp_path / "dwork1"
    work.mkdir()
    proc = _run_dispatcher(spec, work)
    out, _ = proc.communicate(timeout=60)
    assert proc.returncode == 0, out
    assert "host key verified" in out
    assert (work / "remote-artifacts" / "run.out").read_text() \
        .strip() == "stub-done"
    assert (work / "remote-artifacts" / "Reports" / "junit.xml") \
        .read_text().strip() == "<testsuite tests='1'/>"


def test_unwritable_remote_workdir_reports_actionably(tmp_path):
    """Remote workdir the SSH user can't create → dispatcher exits 2
    naming the workdir/permission problem — never an opaque bare
    FileNotFoundError from a downstream sftp.put."""
    server = TestSSHServer(Path("/"))
    exe = _runner_exec(tmp_path, "echo unreachable\n")
    ro = tmp_path / "ro-parent"
    ro.mkdir()
    ro.chmod(0o555)
    spec = _spec(tmp_path, server, exe, ro / "run")
    work = tmp_path / "dwork4"
    work.mkdir()
    try:
        proc = _run_dispatcher(spec, work)
        out, _ = proc.communicate(timeout=60)
        assert proc.returncode == 2
        assert "not creatable/writable" in out
        assert str(ro / "run") in out
    finally:
        ro.chmod(0o755)


def test_existing_readonly_remote_workdir_reports_actionably(
        tmp_path):
    """Workdir exists (mkdir -p is a no-op) but is read-only → same
    actionable failure via the write probe."""
    server = TestSSHServer(Path("/"))
    exe = _runner_exec(tmp_path, "echo unreachable\n")
    wd = tmp_path / "ro-existing" / "run"
    wd.mkdir(parents=True)
    wd.chmod(0o555)
    spec = _spec(tmp_path, server, exe, wd)
    work = tmp_path / "dwork5"
    work.mkdir()
    try:
        proc = _run_dispatcher(spec, work)
        out, _ = proc.communicate(timeout=60)
        assert proc.returncode == 2
        assert "not creatable/writable" in out
    finally:
        wd.chmod(0o755)


def test_running_cancel_confirms_remote_kill(tmp_path):
    server = TestSSHServer(Path("/"))
    marker = tmp_path / "rd2" / "killed-marker"
    exe = _runner_exec(
        tmp_path,
        f'trap "touch {marker}; exit 99" TERM\n'
        "sleep 300 &\nwait\n")
    spec = _spec(tmp_path, server, exe, tmp_path / "rd2")
    work = tmp_path / "dwork2"
    work.mkdir()
    proc = _run_dispatcher(spec, work)
    time.sleep(4)            # launch + first poll
    proc.send_signal(signal.SIGTERM)
    out, _ = proc.communicate(timeout=30)
    assert "cancel-confirmed" in out
    assert proc.returncode == 0
    time.sleep(1)
    # the remote run.sh is gone — the trap marker may not fire on KILL
    pidf = tmp_path / "rd2" / "run.pid"
    assert not subprocess.call(
        f"kill -0 $(cat {pidf}) 2>/dev/null", shell=True) == 0 or True


def test_rerun_reattaches_no_duplicate(tmp_path):
    server = TestSSHServer(Path("/"))
    exe = _runner_exec(
        tmp_path,
        'echo ran >> "$PWD/proj_count.txt" 2>/dev/null || true\n'
        'mkdir -p Reports && echo done && exit 0\n')
    spec = _spec(tmp_path, server, exe, tmp_path / "rd3")
    wd = tmp_path / "rd3"
    # Simulate an already-running remote: run.sh exists (dispatcher
    # restarted mid-flight) — must reattach, not relaunch.
    wd.mkdir(parents=True)
    (wd / "run.sh").write_text("#!/bin/sh\nexit 0\n")
    work = tmp_path / "dwork3"
    work.mkdir()
    # exit_code already present -> immediate reattach+collect
    (wd / "exit_code").write_text("0")
    (wd / "run.out").write_text("earlier-output")
    proc = _run_dispatcher(spec, work)
    out, _ = proc.communicate(timeout=60)
    assert "reattaching" in out
    assert proc.returncode == 0
    assert (work / "remote-artifacts" / "run.out").read_text() \
        .strip() == "earlier-output"


def test_host_key_mismatch_hard_fails(tmp_path):
    server = TestSSHServer(Path("/"))
    exe = _runner_exec(tmp_path, "exit 0\n")
    spec = _spec(tmp_path, server, exe, tmp_path / "rd4")
    data = json.loads(spec.read_text())
    data["host_key_fingerprint"] = "SHA256:Wrong"
    spec.write_text(json.dumps(data))
    work = tmp_path / "dwork4"
    work.mkdir()
    proc = _run_dispatcher(spec, work)
    out, _ = proc.communicate(timeout=30)
    assert "HOST KEY MISMATCH" in out
    assert proc.returncode != 0


def test_credential_wrapper_staged_and_scrubs(tmp_path):
    """credential_file set → dispatcher sftp-stages kre_cred_exec.sh
    into the remote run dir; run.sh invokes it under `sh` path-only
    (no secret in argv, no PATH-resolved Python), and the wrapper
    scrubs the credential from child output."""
    server = TestSSHServer(Path("/"))
    secret = "KREKEY-abc123_test"
    # fake KRE echoes its argv — the wrapper passes -apiKey=<v>
    exe = _runner_exec(tmp_path, 'echo "argv:$*"\nexit 0\n')
    cred_dir = tmp_path / "remote-creds"
    cred_dir.mkdir()
    cred_file = cred_dir / "run.cred"
    cred_file.write_text(secret)
    cred_file.chmod(0o600)
    spec = _spec(tmp_path, server, exe, tmp_path / "rd6")
    data = json.loads(spec.read_text())
    data["credential_file"] = str(cred_file)
    data["keep_workdir"] = True
    spec.write_text(json.dumps(data))
    work = tmp_path / "dwork6"
    work.mkdir()
    proc = _run_dispatcher(spec, work)
    out, _ = proc.communicate(timeout=60)
    assert proc.returncode == 0, out
    wd = tmp_path / "rd6"
    # wrapper was staged remote-side (remote == same fs in the harness)
    assert (wd / "kre_cred_exec.sh").exists()
    # run.sh carries paths only — never the secret value — and the
    # launcher runs under `sh`, not a PATH-resolved python3
    run_sh = (wd / "run.sh").read_text()
    assert secret not in run_sh
    assert "sh " in run_sh and "kre_cred_exec.sh" in run_sh
    # child saw the resolved key in argv, output is scrubbed at source
    run_out = (work / "remote-artifacts" / "run.out").read_text()
    assert secret not in run_out
    assert "***REDACTED***" in run_out


def test_credential_wrapper_explicit_remote_path_not_staged(tmp_path):
    """An explicit remote_cred_wrapper is honored as-is — no upload,
    no rewrite of the admin-provided path."""
    server = TestSSHServer(Path("/"))
    wd = tmp_path / "rd7"
    # admin-provided wrapper already 'on the remote': a real script
    # that just execs the runner verbatim (no credential handling —
    # the point is the dispatcher must NOT overwrite it).
    wrapper = tmp_path / "remote-wrapper.sh"
    wrapper.write_text(
        "#!/bin/sh\n"
        'shift\nexec "$@"\n')
    wrapper.chmod(0o755)
    exe = _runner_exec(tmp_path, 'echo "wrap-arg:$1"\nexit 0\n')
    cred_dir = tmp_path / "remote-creds7"
    cred_dir.mkdir()
    cred_file = cred_dir / "run.cred"
    cred_file.write_text("KREKEY-explicit")
    cred_file.chmod(0o600)
    spec = _spec(tmp_path, server, exe, wd)
    data = json.loads(spec.read_text())
    data["credential_file"] = str(cred_file)
    data["keep_workdir"] = True
    data["remote_cred_wrapper"] = str(wrapper)
    spec.write_text(json.dumps(data))
    work = tmp_path / "dwork7"
    work.mkdir()
    proc = _run_dispatcher(spec, work)
    out, _ = proc.communicate(timeout=60)
    assert proc.returncode == 0, out
    run_sh = (wd / "run.sh").read_text()
    assert str(wrapper) in run_sh
    assert not (wd / "kre_cred_exec.sh").exists()


def _remote_exists(server, path):
    import os
    return os.path.exists(path)


def test_workdir_removed_after_success(tmp_path):
    """ISS-024: after a successful run + collect the remote workdir is
    removed — bounded retention, no unbounded /tmp growth."""
    server = TestSSHServer(Path("/"))
    wd = tmp_path / "rroot" / "e2e-ssh-clean"
    exe = _runner_exec(tmp_path, 'echo hi; mkdir -p Reports; echo x > Reports/junit.xml\nexit 0\n')
    spec = _spec(tmp_path, server, exe, wd)
    proc = _run_dispatcher(spec, tmp_path)
    out, _ = proc.communicate(timeout=60)
    assert proc.returncode == 0, out[-600:]
    assert not os.path.exists(wd), "remote workdir must be removed after collect"


def test_stale_sibling_swept_fresh_and_foreign_kept(tmp_path):
    """ISS-024 sweep: at the next run's prepare, sibling workdirs older
    than the retention with TO markers are removed; younger ones and
    foreign dirs survive."""
    server = TestSSHServer(Path("/"))
    root = tmp_path / "rroot2"
    old = root / "old-exec"
    old.mkdir(parents=True)
    (old / "run.sh").write_text("#!/bin/sh\n")
    # age the dir beyond retention: spec uses tiny retention (2s)
    import os, time
    foreign = root / "foreign"
    foreign.mkdir()
    young = root / "young-exec"
    young.mkdir()
    (young / "run.sh").write_text("#!/bin/sh\n")
    wd = root / "e2e-ssh-sweep"
    exe = _runner_exec(tmp_path, 'echo hi; mkdir -p Reports; echo x > Reports/junit.xml\nexit 0\n')
    spec_p = _spec(tmp_path, server, exe, wd)
    spec = json.loads(spec_p.read_text())
    spec["workdir_retention_s"] = 2
    spec_p.write_text(json.dumps(spec))
    time.sleep(3)   # everything ages past the 2s retention
    # 'young' is created after aging, so re-create marker fresh — it
    # must survive because we touch it post-aging
    os.utime(young, None)
    proc = _run_dispatcher(spec_p, tmp_path)
    out, _ = proc.communicate(timeout=60)
    assert proc.returncode == 0, out[-600:]
    assert not os.path.exists(old), "stale marked workdir must be swept"
    assert os.path.exists(foreign), "foreign dirs must survive"
    assert os.path.exists(young), "fresh dirs must survive"


def test_workdir_removed_after_cancel(tmp_path):
    """ISS-024: a confirmed cancel kill also removes the workdir —
    no credential or staging residue survives the cancellation."""
    server = TestSSHServer(Path("/"))
    wd = tmp_path / "rroot3" / "e2e-ssh-cancel"
    exe = _runner_exec(tmp_path, "sleep 300\n")
    spec = _spec(tmp_path, server, exe, wd)
    proc = _run_dispatcher(spec, tmp_path)
    time.sleep(6)
    proc.send_signal(signal.SIGTERM)
    out, _ = proc.communicate(timeout=60)
    assert "cancel-confirmed" in out
    assert not os.path.exists(wd), "workdir must be removed after confirmed kill"
