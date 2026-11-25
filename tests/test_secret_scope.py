"""Credential authorization scope: grants, pending associations,
migration derivation, and dispatch-time denial (§12)."""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from testorchestrator import create_app
from testorchestrator.config import Config
from testorchestrator.dispatch import DispatchError, _resolve_runtime_secret
from testorchestrator.execution import Runner, RuntimeConnection, SecretRef
from testorchestrator.extensions import db
from testorchestrator.secrets_store import (record_pending_association,
                                            scope_allows, store_secret,
                                            update_secret_scope)
from testorchestrator.settings import mark_setup_complete


class _Cfg(Config):
    TESTING = True
    SECRET_KEY = "x"
    WTF_CSRF_ENABLED = False


def _app(tmp):
    class C(_Cfg):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp/'t.db'}"
    return create_app(C)


def _runtime(rt_id="rt1", runner_id="rn1", ref="k"):
    return RuntimeConnection(
        id=rt_id, name="t", runner_id=runner_id, transport="local",
        executable_path="/x", credential_ref=ref, runtime_kind="kre")


def test_scope_default_deny_and_grant_match(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        db.create_all()
        os.environ["TO_SECRET_KEY_FILE"] = str(tmp_path / "s.key")
        store_secret(app, "k", "runtime", "v")
        assert not scope_allows("k", project_id="p1", runtime_id="rt1")
        update_secret_scope("k", {
            "grants": [{"project_ids": ["p1"], "runtime_ids": ["rt1"],
                        "runner_ids": ["rn1"]}],
            "pending": []})
        assert scope_allows("k", project_id="p1", runtime_id="rt1",
                            runner_id="rn1")
        assert not scope_allows("k", project_id="p2",
                                runtime_id="rt1", runner_id="rn1")
        assert not scope_allows("k", project_id="p1",
                                runtime_id="rt2", runner_id="rn1")


def test_pending_never_bypasses(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        db.create_all()
        os.environ["TO_SECRET_KEY_FILE"] = str(tmp_path / "s.key")
        store_secret(app, "k", "runtime", "v")
        record_pending_association("k", "rt9", "rn1")
        record_pending_association("k", "rt9", "rn1")  # idempotent
        row = SecretRef.query.filter_by(name="k").one()
        pending = json.loads(row.scope_json)["pending"]
        assert len(pending) == 1
        assert not scope_allows("k", runtime_id="rt9", runner_id="rn1")


def test_dispatch_denies_unscoped(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        db.create_all()
        mark_setup_complete()
        os.environ["TO_SECRET_KEY_FILE"] = str(tmp_path / "s.key")
        store_secret(app, "k", "runtime", "v")
        rt = _runtime()
        db.session.add(Runner(id="rn1", name="r"))
        db.session.add(rt)
        db.session.commit()
        with unittest.TestCase().assertRaises(DispatchError) as cm:
            _resolve_runtime_secret(rt, project_id="p1")
        assert "credential-scope" in str(cm.exception)
        update_secret_scope("k", {
            "grants": [{"project_ids": [], "runtime_ids": ["rt1"],
                        "runner_ids": []}],
            "pending": []})
        assert _resolve_runtime_secret(rt, project_id="p1") == "v"


def test_migration_derives_grants(tmp_path):
    """Backfill derives a grant per concrete referencing runtime and
    flags every pre-existing secret for admin review."""
    import sqlalchemy as sa
    from migrations.versions import n2b3c4d5e6f7_secret_scope as mig

    eng = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with eng.connect() as bind:
        bind.execute(sa.text(
            "CREATE TABLE secret_refs (name TEXT, kind TEXT)"))
        bind.execute(sa.text(
            "CREATE TABLE runtime_connections "
            "(id TEXT, runner_id TEXT, credential_ref TEXT, "
            "allowed_projects TEXT)"))
        bind.execute(sa.text(
            "INSERT INTO secret_refs VALUES ('k','runtime'),"
            "('u','runtime'),('g','git')"))
        bind.execute(sa.text(
            "INSERT INTO runtime_connections VALUES "
            "('rt1','rn1','k','[\"p1\",\"p2\"]'),('rt2','rn2','k','[]')"))
        g = mig._derive_scope(bind, "k")
        assert mig._derive_scope(bind, "g") == []
    assert g == [
        {"project_ids": ["p1", "p2"], "runtime_ids": ["rt1"],
         "runner_ids": ["rn1"]},
        {"project_ids": [], "runtime_ids": ["rt2"],
         "runner_ids": ["rn2"]}]


if __name__ == "__main__":
    unittest.main()
