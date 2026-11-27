"""Installer upgrade defense — regression for the 2.6.0 upgrade cell.

The production-like upgrade cell proved the failure chain: a service
unit missing from the documented stop list survived, held the payload
python busy (ETXTBSY), and the payload copy crashed mid-write — a
half-written hybrid install with every service down. The owner ruled
this a release blocker and chose defense in depth: the installer now
stops running testorchestrator-* units itself before copying, and
refuses to write into a tree any process still references.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import install as inst  # noqa: E402  scripts/install.py


def _spawn_holder(payload: Path):
    """A live process whose command line references the payload tree."""
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)",
         str(payload)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_payload_processes_detects_holder(tmp_path):
    payload = tmp_path / "payload"
    payload.mkdir()
    proc = _spawn_holder(payload)
    try:
        time.sleep(0.3)
        hits = inst._payload_processes(payload)
        assert any(pid == proc.pid for pid, _ in hits), \
            f"holder pid {proc.pid} not detected: {hits}"
    finally:
        proc.kill()
        proc.wait()
    # gone after exit — no false positive on a quiet tree
    time.sleep(0.3)
    assert not inst._payload_processes(payload)


def test_payload_processes_ignores_unrelated(tmp_path):
    payload = tmp_path / "payload"
    payload.mkdir()
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.2)
        assert not inst._payload_processes(payload)
    finally:
        proc.kill()
        proc.wait()


class _Args:
    dry_run = False


def test_stop_refuses_busy_tree(tmp_path, monkeypatch):
    """A survivor after the service stop must abort BEFORE any write."""
    monkeypatch.setattr(inst, "_active_to_units", lambda: [])
    payload = tmp_path / "payload"
    payload.mkdir()
    proc = _spawn_holder(payload)
    try:
        time.sleep(0.3)
        with pytest.raises(SystemExit) as exc:
            inst.stop_services_before_payload_copy(_Args(), payload)
        assert "refusing to overwrite a busy tree" in str(exc.value)
        assert str(proc.pid) in str(exc.value)
    finally:
        proc.kill()
        proc.wait()


def test_stop_clean_tree_proceeds(tmp_path, monkeypatch):
    monkeypatch.setattr(inst, "_active_to_units", lambda: [])
    payload = tmp_path / "payload"
    payload.mkdir()
    # must simply return — no SystemExit
    inst.stop_services_before_payload_copy(_Args(), payload)


def test_stop_orders_units_stop_when_root(monkeypatch, tmp_path):
    """When root with systemd present, every active testorchestrator-*
    unit is stopped before the copy — including units unknown to the
    documented procedure (the ssh dispatcher was the cell's survivor)."""
    calls = []
    monkeypatch.setattr(inst, "_active_to_units",
                        lambda: ["testorchestrator-web.service",
                                 "testorchestrator-buildbot-ssh.service"])
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(inst.shutil, "which", lambda x: "/bin/systemctl")
    real_run = subprocess.run

    def fake_run(argv, **kw):
        calls.append(argv)
        return real_run(["true"])

    monkeypatch.setattr(inst.subprocess, "run", fake_run)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    payload = tmp_path / "payload"  # does not exist — scan skipped
    inst.stop_services_before_payload_copy(_Args(), payload)
    stops = [c for c in calls if isinstance(c, list) and "stop" in c]
    assert stops, f"no systemctl stop issued: {calls}"
    assert "testorchestrator-buildbot-ssh.service" in stops[0]
    assert "testorchestrator-web.service" in stops[0]


# --- frozen toctl path (testorchestrator/cli.py) — same defense ---

def test_cli_payload_processes_detects_holder(tmp_path):
    from testorchestrator import cli
    payload = tmp_path / "payload"
    payload.mkdir()
    proc = _spawn_holder(payload)
    try:
        time.sleep(0.3)
        hits = cli._payload_processes(payload)
        assert any(pid == proc.pid for pid, _ in hits)
    finally:
        proc.kill()
        proc.wait()


def test_cli_stop_refuses_busy_tree(tmp_path, monkeypatch):
    from testorchestrator import cli
    monkeypatch.setattr(cli, "_active_to_units", lambda: [])
    payload = tmp_path / "payload"
    payload.mkdir()
    proc = _spawn_holder(payload)
    try:
        time.sleep(0.3)
        rc = cli._stop_services_before_copy(payload, dry_run=False)
        assert rc == 2
    finally:
        proc.kill()
        proc.wait()


def test_cli_stop_clean_tree_proceeds(tmp_path, monkeypatch):
    from testorchestrator import cli
    monkeypatch.setattr(cli, "_active_to_units", lambda: [])
    payload = tmp_path / "payload"
    payload.mkdir()
    assert cli._stop_services_before_copy(payload, dry_run=False) == 0
