"""Application-level secret-authorization acceptance (owner matrix §1).

Complements test_secret_scope.py (unit-level scope math) with coverage
through the product surfaces: listing visibility, forged references,
effective project restrictions, claim-time revocation, denial ordering
vs decryption, pending-association non-bypass, runtime create/edit
recording, and admin scope-edit audit.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from testorchestrator.dispatch import DispatchError, _resolve_runtime_secret
from testorchestrator.execution import (Runner, RuntimeConnection,
                                        SecretRef)
from testorchestrator.extensions import db
from testorchestrator.models import AuditEvent
from testorchestrator.secrets_store import (list_secret_meta,
                                            record_pending_association,
                                            scope_allows, store_secret,
                                            update_secret_scope)

from conftest import login


def _runtime(rt_id="rt1", runner_id="rn1", ref="k", allowed="[]"):
    return RuntimeConnection(
        id=rt_id, name="t", runner_id=runner_id, transport="local",
        executable_path="/x", credential_ref=ref, runtime_kind="kre",
        allowed_projects=allowed)


def _err_kind(fn):
    try:
        fn()
        return "RESOLVED"
    except DispatchError as exc:
        assert "credential" not in str(exc) or "SYNTHETIC" not in str(exc)
        return str(exc)
    except Exception as exc:
        return f"{type(exc).__name__}:{exc}"


def test_listing_never_discloses_material(app):
    """Secrets listing (API + admin page) exposes names/kinds/scope —
    never ciphertext or plaintext."""
    with app.app_context():
        os.environ["TO_SECRET_KEY_FILE"] = os.path.join(
            app.instance_path, "s.key")
        store_secret(app, "k-vis", "runtime", "SYNTHETIC-VALUE-99")
        meta = list_secret_meta()
        assert any(m["name"] == "k-vis" for m in meta)
        blob = json.dumps(meta)
        assert "SYNTHETIC-VALUE-99" not in blob
        row = SecretRef.query.filter_by(name="k-vis").first()
        assert row.encrypted.decode() not in blob
        assert not any("encrypted" in m or "value" in m for m in meta)


def test_forged_reference_denials(app):
    """Forged/unusable refs deny as config before any decryption:
    nonexistent name, wrong-kind secret."""
    with app.app_context():
        os.environ["TO_SECRET_KEY_FILE"] = os.path.join(
            app.instance_path, "s.key")
        db.session.add(_runtime(ref="no-such"))
        db.session.add(_runtime(rt_id="rt2", ref="bb"))
        store_secret(app, "bb", "buildbot", "x", internal=True)
        db.session.commit()
        assert "does not exist" in _err_kind(
            lambda: _resolve_runtime_secret(
                db.session.get(RuntimeConnection, "rt1")))
        assert "'buildbot'-kind" in _err_kind(
            lambda: _resolve_runtime_secret(
                db.session.get(RuntimeConnection, "rt2")))


def test_project_restriction_effective_not_copied(app):
    """A grant carrying project_ids actually denies other projects —
    migrated allowed_projects restrictions remain *effective*."""
    with app.app_context():
        os.environ["TO_SECRET_KEY_FILE"] = os.path.join(
            app.instance_path, "s.key")
        db.session.add(_runtime())
        store_secret(app, "k", "runtime", "v")
        update_secret_scope("k", {
            "grants": [{"project_ids": ["p-allowed"],
                        "runtime_ids": [], "runner_ids": []}],
            "pending": []})
        db.session.commit()
        rt = db.session.get(RuntimeConnection, "rt1")
        assert _resolve_runtime_secret(rt, project_id="p-allowed") == "v"
        err = _err_kind(lambda: _resolve_runtime_secret(
            rt, project_id="p-forbidden"))
        assert "credential-scope" in err


def test_runner_restriction_effective(app):
    """Grant runner_ids binds the credential to that runner only."""
    with app.app_context():
        os.environ["TO_SECRET_KEY_FILE"] = os.path.join(
            app.instance_path, "s.key")
        db.session.add(_runtime())
        db.session.add(_runtime(rt_id="rt2", runner_id="rn-other"))
        store_secret(app, "k", "runtime", "v")
        update_secret_scope("k", {
            "grants": [{"project_ids": [], "runtime_ids": [],
                        "runner_ids": ["rn1"]}],
            "pending": []})
        db.session.commit()
        assert _resolve_runtime_secret(
            db.session.get(RuntimeConnection, "rt1")) == "v"
        assert "credential-scope" in _err_kind(
            lambda: _resolve_runtime_secret(
                db.session.get(RuntimeConnection, "rt2")))


def test_claim_time_revocation(app):
    """Revoking the grant denies the NEXT resolve — enforcement is
    re-evaluated at claim time, not cached."""
    with app.app_context():
        os.environ["TO_SECRET_KEY_FILE"] = os.path.join(
            app.instance_path, "s.key")
        db.session.add(_runtime())
        store_secret(app, "k", "runtime", "v")
        update_secret_scope("k", {
            "grants": [{"project_ids": [], "runtime_ids": ["rt1"],
                        "runner_ids": []}],
            "pending": []})
        db.session.commit()
        rt = db.session.get(RuntimeConnection, "rt1")
        assert _resolve_runtime_secret(rt) == "v"
        update_secret_scope("k", {"grants": [], "pending": []})
        assert "credential-scope" in _err_kind(
            lambda: _resolve_runtime_secret(rt))


def test_denial_before_decryption(app):
    """Scope denial precedes decryption: a corrupt ciphertext on a
    denied secret still reports credential-scope (not a decrypt
    failure) — delivery/decryption never happens after denial."""
    with app.app_context():
        os.environ["TO_SECRET_KEY_FILE"] = os.path.join(
            app.instance_path, "s.key")
        db.session.add(_runtime())
        store_secret(app, "k", "runtime", "v")
        row = SecretRef.query.filter_by(name="k").first()
        row.encrypted = b"corrupt-not-fernet"
        db.session.commit()
        rt = db.session.get(RuntimeConnection, "rt1")
        # Denied: scope error, decrypt never attempted.
        assert "credential-scope" in _err_kind(
            lambda: _resolve_runtime_secret(rt))
        # Granted: decrypt attempted, masked infrastructure error.
        update_secret_scope("k", {
            "grants": [{"project_ids": [], "runtime_ids": [],
                        "runner_ids": []}],
            "pending": []})
        err = _err_kind(lambda: _resolve_runtime_secret(rt))
        assert "could not be resolved" in err
        assert "credential-scope" not in err


def test_pending_association_never_grants(app):
    """Recording a pending association (the association-time action)
    does NOT authorize use — denial stands until an admin grant."""
    with app.app_context():
        os.environ["TO_SECRET_KEY_FILE"] = os.path.join(
            app.instance_path, "s.key")
        db.session.add(_runtime())
        store_secret(app, "k", "runtime", "v")
        db.session.commit()
        record_pending_association("k", "rt1", "rn1")
        rt = db.session.get(RuntimeConnection, "rt1")
        assert "credential-scope" in _err_kind(
            lambda: _resolve_runtime_secret(rt))
        assert not scope_allows("k", project_id="p1", runtime_id="rt1",
                                runner_id="rn1")


def test_manual_runtime_create_records_pending(client, app):
    """Manual creation path: saving a credential_ref on a runtime
    records a pending association — never an implicit grant."""
    login(client, "admin")
    with app.app_context():
        os.environ["TO_SECRET_KEY_FILE"] = os.path.join(
            app.instance_path, "s.key")
        store_secret(app, "k-man", "runtime", "v")
        r = Runner(name="loc", connection_mode="local",
                   os_arch="local", max_slots=4)
        db.session.add(r)
        db.session.commit()
        rid = r.id
    resp = client.post("/system/infrastructure/runtimes", data={
        "name": "rt-manual", "runner_id": rid,
        "runtime_kind": "kre", "executable_path": "/x",
        "credential_ref": "k-man"}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        scope = json.loads(
            SecretRef.query.filter_by(name="k-man").first().scope_json)
        rt = RuntimeConnection.query.filter_by(
            name="rt-manual").first()
        assert rt is not None
        assert scope["grants"] == []
        assert any(p.get("runtime_id") == rt.id
                   for p in scope["pending"])
        # And the runtime remains denied for use.
        assert "credential-scope" in _err_kind(
            lambda: _resolve_runtime_secret(rt))


def test_runtime_edit_records_pending(client, app):
    """Runtime edit path (third save site): assigning a credential_ref
    to an existing runtime records pending, not a grant."""
    login(client, "admin")
    with app.app_context():
        os.environ["TO_SECRET_KEY_FILE"] = os.path.join(
            app.instance_path, "s.key")
        store_secret(app, "k-edit", "runtime", "v")
        db.session.add(_runtime(ref=""))
        db.session.commit()
    rt_id = "rt1"
    resp = client.post(f"/system/runtimes/{rt_id}/edit",
                       data={"name": "t", "credential_ref": "k-edit"},
                       follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        scope = json.loads(
            SecretRef.query.filter_by(
                name="k-edit").first().scope_json)
        assert any(p.get("runtime_id") == rt_id
                   for p in scope["pending"])
        assert scope["grants"] == []


def test_scope_edit_route_audits_and_role_gates(client, app):
    """Admin scope edit is audited; non-admin roles are denied; saving
    clears the migration-review flag."""
    login(client, "admin")
    with app.app_context():
        os.environ["TO_SECRET_KEY_FILE"] = os.path.join(
            app.instance_path, "s.key")
        store_secret(app, "k-scope", "runtime", "v")
        row = SecretRef.query.filter_by(name="k-scope").first()
        row.migration_pending = True
        db.session.commit()
    resp = client.post("/system/secrets/k-scope/scope", data={
        "scope": json.dumps({
            "grants": [{"project_ids": ["p1"], "runtime_ids": [],
                        "runner_ids": []}],
            "pending": []})}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        row = SecretRef.query.filter_by(name="k-scope").first()
        assert not row.migration_pending
        assert scope_allows("k-scope", project_id="p1")
        ev = AuditEvent.query.filter_by(
            event="secret.scope_updated").order_by(
            AuditEvent.id.desc()).first()
        assert ev is not None and "k-scope" in (ev.detail or "")
    # Non-admin denied — tester role cannot administer scope.
    login(client, "tester")
    resp = client.post("/system/secrets/k-scope/scope", data={
        "scope": json.dumps({"grants": [], "pending": []})},
        follow_redirects=False)
    assert resp.status_code in (302, 403)
    with app.app_context():
        assert scope_allows("k-scope", project_id="p1")  # unchanged


def test_secrets_page_renders_names_only(client, app):
    """GET /secrets (admin) lists names/kinds — the page body never
    embeds ciphertext or plaintext material."""
    login(client, "admin")
    with app.app_context():
        os.environ["TO_SECRET_KEY_FILE"] = os.path.join(
            app.instance_path, "s.key")
        store_secret(app, "k-page", "runtime", "SYNTHETIC-PAGE-77")
        enc = SecretRef.query.filter_by(
            name="k-page").first().encrypted
    resp = client.get("/system/secrets")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "k-page" in body
    assert "SYNTHETIC-PAGE-77" not in body
    assert enc.decode() not in body
