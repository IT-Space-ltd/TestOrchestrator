

def test_exposed_secret_refused_at_resolution(app):
    """Pre-flight exposure guard (post-incident hardening): a secret
    flagged {"exposed": true} in its metadata must be refused at the
    resolution choke point — every consumer (runtime/ssh/git/buildbot)
    funnels through read_secret, so dispatch can never deliver it."""
    import json as _json
    from testorchestrator.execution import SecretRef
    from testorchestrator.secrets_store import (SecretError, read_secret,
                                                store_secret)
    from testorchestrator.extensions import db
    with app.app_context():
        store_secret(app, "exposed-key", "runtime", "value-never-print")
        row = SecretRef.query.filter_by(name="exposed-key").first()
        row.meta_json = _json.dumps({"exposed": True})
        db.session.commit()
        try:
            read_secret(app, "exposed-key")
            assert False, "exposed secret must be refused"
        except SecretError as exc:
            assert "exposed" in str(exc)
            assert "value-never-print" not in str(exc)
        # unflagged secrets still resolve
        store_secret(app, "healthy-key", "runtime", "fine")
        assert read_secret(app, "healthy-key") == "fine"


def test_exposed_flag_clearable_after_rotation(app):
    """The replacement workflow: store the rotated value, clear the
    flag, resolution works again — the guard never destroys lineage."""
    import json as _json
    from testorchestrator.execution import SecretRef
    from testorchestrator.secrets_store import read_secret, store_secret
    from testorchestrator.extensions import db
    with app.app_context():
        store_secret(app, "rot-key", "runtime", "old-value")
        row = SecretRef.query.filter_by(name="rot-key").first()
        row.meta_json = _json.dumps({"exposed": True})
        db.session.commit()
        store_secret(app, "rot-key", "runtime", "new-value")
        row = SecretRef.query.filter_by(name="rot-key").first()
        row.meta_json = "{}"
        db.session.commit()
        assert read_secret(app, "rot-key") == "new-value"
