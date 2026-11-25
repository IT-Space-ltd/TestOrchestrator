"""KRE licensing modes: the dispatch gate must be licensing-mode
aware (online/offline/private), offline provisioning must install
only TestOrchestrator-owned to-*.lic files under the execution
account's ~/.katalon/license, and no path may silently weaken the
online credential requirement or produce a false successful run.
"""
import json
import os
import stat
from pathlib import Path

import pytest

from testorchestrator import buildbot_cfg
from testorchestrator.adapters import kre as kre_adapter
from testorchestrator.dispatch import (_install_licenses_local,
                                       _kre_licensing_gate,
                                       _resolve_license_secrets,
                                       _stage_license_pack,
                                       DispatchError)
from testorchestrator.execution import (Execution, RuntimeConnection,
                                        SecretRef)
from testorchestrator.extensions import db
from testorchestrator.secrets_store import (store_secret,
                                            update_secret_scope)

from conftest import login  # noqa: F401


def _rt(mode="online", cred="", cred_file="", refs="[]", srv="",
        rid="r1"):
    return RuntimeConnection(
        id=rid, name="t", runner_id="rn1", transport="local",
        executable_path="/x/katalonc", credential_ref=cred,
        credential_file=cred_file, runtime_kind="kre",
        licensing_mode=mode, license_refs=refs,
        license_server_url=srv)


class TestGate:
    """_kre_licensing_gate — the missing-credential gate is now
    licensing-mode aware; online keeps the historical contract."""

    def test_online_requires_credential(self, app):
        with app.app_context():
            rt = _rt()
            assert "credential" in _kre_licensing_gate(rt)

    def test_online_ok_with_ref_or_file(self, app):
        with app.app_context():
            assert _kre_licensing_gate(_rt(cred="k")) == ""
            assert _kre_licensing_gate(_rt(cred_file="/c/f")) == ""

    def test_offline_needs_no_api_key(self, app):
        """The whole point: an offline runtime must NOT fail merely
        because an online API-key reference is absent."""
        with app.app_context():
            rt = _rt(mode="offline")
            assert _kre_licensing_gate(rt) == ""

    def test_offline_validates_managed_refs(self, app):
        with app.app_context():
            db.session.add(_rt(mode="offline",
                               refs='["missing-lic"]'))
            db.session.commit()
            err = _kre_licensing_gate(
                db.session.get(RuntimeConnection, "r1"))
            assert "does not exist" in err
            # wrong-kind secret is equally a config error
            os.environ["TO_SECRET_KEY_FILE"] = os.path.join(
                app.instance_path, "s.key")
            store_secret(app, "a-git", "git", "u:t")
            rt = db.session.get(RuntimeConnection, "r1")
            rt.license_refs = '["a-git"]'
            assert "-kind" in _kre_licensing_gate(rt)

    def test_private_requires_url_and_credential(self, app):
        with app.app_context():
            rt = _rt(mode="private", cred="k")
            assert "server URL" in _kre_licensing_gate(rt)
            rt2 = _rt(mode="private", srv="https://lic.internal")
            assert "credential" in _kre_licensing_gate(rt2)
            assert _kre_licensing_gate(
                _rt(mode="private", cred="k",
                    srv="https://lic.internal")) == ""

    def test_unknown_mode_behaves_as_online(self, app):
        """A mistyped mode must not weaken the credential gate."""
        with app.app_context():
            rt = _rt(mode="hybird")  # typo + deliberately no "hybrid"
            assert "credential" in _kre_licensing_gate(rt)


class TestArgs:
    def test_server_url_flag(self):
        args = kre_adapter.build_args(
            executable="katalonc", project_path="/p/x.prj",
            suite_path="Test Suites/s", report_dir="/r",
            server_url="https://lic.internal")
        assert "-serverUrl=https://lic.internal" in args

    def test_no_server_url_flag_when_empty(self):
        args = kre_adapter.build_args(
            executable="katalonc", project_path="/p/x.prj",
            suite_path="Test Suites/s", report_dir="/r")
        assert not any(a.startswith("-serverUrl") for a in args)


class TestClassify:
    """to_license: provisioning markers split infra vs config like
    the credential launcher; offline KRE verdicts classify as
    license."""

    def _res(self, tail, status=1):
        r = kre_adapter.InvocationResult(exit_status=status)
        return r

    def test_marker_infra(self):
        assert kre_adapter.classify_error(
            self._res("x"),
            "to_license: cannot create license dir /u/.katalon/"
            "license") == "infrastructure"

    def test_marker_config(self):
        assert kre_adapter.classify_error(
            self._res("x"),
            "to_license: license install failed for to-ab12.lic: "
            "conflict") == "config"

    def test_offline_kre_verdict_is_license(self):
        tail = ("Cannot execute this test suite. There is no Katalon "
                "Runtime Engine and TestCloud license available.")
        assert kre_adapter.classify_error(self._res(tail), tail) \
            == "license"


class TestPackStaging:
    def test_content_addressed_names(self, app, tmp_path):
        stage, files = buildbot_cfg.write_run_license_pack(
            "ex1", [b"lic-a-body", b"lic-b-body"])
        assert len(files) == 2
        names = {f["name"] for f in files}
        assert all(n.startswith("to-") and n.endswith(".lic")
                   for n in names)
        import tarfile
        with tarfile.open(stage) as tf:
            assert set(tf.getnames()) == names
        assert (Path(stage).stat().st_mode & 0o777) == 0o600


class TestLocalInstall:
    """Local-target provisioning: only to-* files, 0600, marker
    ledger, idempotent, operator files untouched."""

    def _lic_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "testorchestrator.dispatch._lic_dir_home",
            lambda: str(tmp_path / "licdir"))
        return tmp_path / "licdir"

    def test_install_and_idempotent(self, app, tmp_path,
                                    monkeypatch):
        ldir = self._lic_home(tmp_path, monkeypatch)
        with app.app_context():
            names = _install_licenses_local(None, [b"lic-x"])
        f = ldir / names[0]
        assert f.exists()
        assert names[0].startswith("to-")
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
        marker = (ldir / ".to_managed").read_text()
        assert names[0] in marker
        # second run is a no-op, operator file untouched
        (ldir / "operator.lic").write_bytes(b"theirs")
        with app.app_context():
            _install_licenses_local(None, [b"lic-x"])
        assert (ldir / "operator.lic").read_bytes() == b"theirs"


class TestResolveSecrets:
    def test_scope_denied_before_decrypt(self, app):
        with app.app_context():
            os.environ["TO_SECRET_KEY_FILE"] = os.path.join(
                app.instance_path, "s.key")
            db.session.add(_rt(mode="offline", refs='["lic1"]'))
            store_secret(app, "lic1", "license", "LIC-BODY")
            update_secret_scope("lic1", {
                "grants": [{"project_ids": ["p-other"],
                            "runtime_ids": [], "runner_ids": []}],
                "pending": []})
            db.session.commit()
            rt = db.session.get(RuntimeConnection, "r1")
            with pytest.raises(DispatchError) as ei:
                _resolve_license_secrets(rt, project_id="p-mine")
            assert "credential-scope" in str(ei.value)

    def test_granted_resolves_bytes(self, app):
        with app.app_context():
            os.environ["TO_SECRET_KEY_FILE"] = os.path.join(
                app.instance_path, "s.key")
            db.session.add(_rt(mode="offline", refs='["lic1"]'))
            store_secret(app, "lic1", "license", "LIC-BODY")
            update_secret_scope("lic1", {
                "grants": [{"project_ids": [],
                            "runtime_ids": ["r1"],
                            "runner_ids": []}],
                "pending": []})
            db.session.commit()
            rt = db.session.get(RuntimeConnection, "r1")
            assert _resolve_license_secrets(rt) == [b"LIC-BODY"]


class TestSpecPlumbing:
    def test_kre_exec_spec_carries_license_install(self):
        class Ex:
            id = "e1"

            @staticmethod
            def snapshot():
                return {}

        spec = buildbot_cfg.kre_exec_spec(
            Ex(), _rt(mode="offline"), ["katalonc", "-x"],
            licenses={"mastersrc": "/st/e1.licpack.tar",
                      "stage": "/st/e1.licpack.tar",
                      "files": [{"name": "to-aa.lic", "sha256": "aa"}]})
        assert spec["license_install"]["files"][0]["name"] == \
            "to-aa.lic"
        spec2 = buildbot_cfg.kre_exec_spec(Ex(), _rt(), ["katalonc"])
        assert "license_install" not in spec2

    def test_ssh_spec_carries_license_install(self, app):
        with app.app_context():
            from testorchestrator.execution import Runner
            r = Runner(name="ssh-r", connection_mode="remote",
                       target_type="ssh", ssh_host="h",
                       ssh_username="u", ssh_workdir="/w")
            db.session.add(r)
            db.session.commit()
            spec_file = buildbot_cfg.write_ssh_run_spec(
                type("E", (), {"id": "e2",
                               "snapshot": staticmethod(
                                   lambda: {})})(),
                r, _rt(mode="offline"), ["-runMode=console"],
                licenses={"stage": "/st/e2.licpack.tar",
                          "files": [{"name": "to-bb.lic",
                                     "sha256": "bb"}]})
            spec = json.loads(Path(spec_file).read_text())
            assert spec["license_install"]["files"][0]["name"] == \
                "to-bb.lic"


class TestProbeScripts:
    def test_posix_probe_reports_licensing(self):
        assert "licensing_mode" in kre_adapter.PROBE_SH
        assert "license_files" in kre_adapter.PROBE_SH
        assert "exec_user" in kre_adapter.PROBE_SH
        assert ".katalon/license" in kre_adapter.PROBE_SH

    def test_windows_probe_reports_licensing(self):
        assert "licensing_mode" in kre_adapter.PROBE_CMD
        assert "license_files" in kre_adapter.PROBE_CMD
        assert "USERPROFILE" in kre_adapter.PROBE_CMD
