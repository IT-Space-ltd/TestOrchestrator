"""install_linux_worker.sh — interpreter range gating.

The bundled bb-wheels carry ABI tags for a fixed python minor range
(cp3XX). The installer must derive that range from the wheels dir and
reject out-of-range interpreters UP FRONT — before useradd/venv —
rather than failing mid-install inside pip's wheel resolution. No
root needed: the gate runs before any privileged action.
"""
import os
import stat
import subprocess
import sys
from pathlib import Path

SCRIPT = str(Path(__file__).parent.parent / "scripts"
             / "install_linux_worker.sh")


def _stub_python(bin_dir: Path, major: int, minor: int) -> None:
    """A 'python3' that answers version probes as (major, minor, 0) by
    rewriting sys.version_info references in the -c snippet, and
    delegates everything else to the real interpreter."""
    stub = bin_dir / "python3"
    real = sys.executable
    stub.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-c" ]; then\n'
        f'  code=$(printf %s "$2" | sed '
        f"'s/sys\\.version_info/({major},{minor},0)/g')\n"
        f'  exec "{real}" -c "$code"\n'
        "fi\n"
        'if [ "$1" = "--version" ]; then\n'
        f'  echo "Python {major}.{minor}.0"; exit 0\n'
        "fi\n"
        f'exec "{real}" "$@"\n')
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
               | stat.S_IXOTH)


def _run(tmp_path: Path, minor: int, extra_args=()):
    bindir = tmp_path / f"bin-{minor}"
    bindir.mkdir(exist_ok=True)
    _stub_python(bindir, 3, minor)
    wheels = tmp_path / "bb-wheels"
    wheels.mkdir(exist_ok=True)
    (wheels / "msgpack-1.0.0-cp312-cp312-manylinux_x86_64.whl") \
        .write_bytes(b"x")
    (wheels / "msgpack-1.0.0-cp311-cp311-manylinux_x86_64.whl") \
        .write_bytes(b"x")
    (wheels / "msgpack-1.0.0-cp310-cp310-manylinux_x86_64.whl") \
        .write_bytes(b"x")
    (wheels / "buildbot_worker-4.3.0-py3-none-any.whl") \
        .write_bytes(b"x")
    pw = tmp_path / "pw"
    pw.write_text("pw\n")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    return subprocess.run(
        ["bash", SCRIPT, "--master", "127.0.0.1:9989",
         "--name", "w1", "--passwd-file", str(pw),
         "--wheels", str(wheels), *extra_args],
        capture_output=True, text=True, env=env, timeout=30)


def test_python_above_wheel_range_rejected_early(tmp_path):
    """3.14 host with cp310-312 wheels → clear upfront refusal, not a
    mid-install wheel-resolution failure."""
    r = _run(tmp_path, 14)
    assert r.returncode == 2
    assert "3.10-3.12" in r.stderr
    assert "Python 3.14.0" in r.stderr
    # refused before ANY privileged action — no useradd/venv attempt
    assert "venv" not in r.stderr.lower()


def test_python_below_wheel_range_rejected_early(tmp_path):
    r = _run(tmp_path, 9)
    assert r.returncode == 2
    assert "3.10-3.12" in r.stderr


def test_python_in_range_passes_gate(tmp_path):
    """3.12 passes the interpreter gate (fails later at useradd —
    unprivileged test env — which proves the gate let it through)."""
    r = _run(tmp_path, 12)
    assert "3.10-3.12 required" not in r.stderr


def test_online_above_range_warns_not_rejects(tmp_path):
    """--online resolves from PyPI where newer interpreters may have
    wheels/sdists — warn but do not hard-refuse."""
    r = _run(tmp_path, 14, extra_args=("--online",))
    assert "outside 3.10-3.12" in r.stderr
    assert "required" not in r.stderr
