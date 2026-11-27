"""secret authorization scope: scope_json grants + migration_pending

Revision ID: n2b3c4d5e6f7
Revises: m1a2b3c4d5e6
Create Date: 2026-11-24

Constrained option A (approved): additive columns only; grants are
DERIVED from concrete existing associations — a runtime-kind secret
referenced by ``runtime_connections.credential_ref`` gets one grant
row per referencing runtime:

    {"project_ids": rt.allowed_projects (as stored),
     "runtime_ids": [rt.id],
     "runner_ids": [rt.runner_id]}

``allowed_projects`` is copied verbatim — a runtime restricted to
specific projects keeps that restriction inside the derived grant;
an empty allowed_projects (runtime already open to all projects)
yields an empty project_ids dimension, which is a wildcard ONLY for
that runtime — never across runtimes or secrets.

Secrets with no referencing association get NO grants (default-deny)
and ``migration_pending`` is set on every migrated secret so the
administrator reviews the derived scope — the flag is advisory and
never bypasses enforcement. Other kinds (git/buildbot/ssh/runner) are
enforced through their own consumers; scoping applies to 'runtime'
KRE credentials at dispatch time.
"""
from alembic import op
import json
import sqlalchemy as sa

revision = "n2b3c4d5e6f7"
down_revision = "m1a2b3c4d5e6"
branch_labels = None
depends_on = None


def _derive_scope(bind, name: str) -> list:
    rows = bind.execute(sa.text(
        "SELECT id, runner_id, allowed_projects FROM "
        "runtime_connections WHERE credential_ref = :n"),
        {"n": name}).fetchall()
    grants = []
    for rt_id, runner_id, allowed in rows:
        try:
            proj = json.loads(allowed or "[]")
        except (TypeError, ValueError):
            proj = []
        grants.append({
            "project_ids": [p for p in proj if isinstance(p, str)],
            "runtime_ids": [rt_id],
            "runner_ids": [runner_id] if runner_id else [],
        })
    return grants


def upgrade() -> None:
    from sqlalchemy import inspect as _inspect
    bind = op.get_bind()
    cols = {c["name"] for c in _inspect(bind).get_columns("secret_refs")}
    if "scope_json" not in cols:
        op.add_column("secret_refs", sa.Column(
            "scope_json", sa.Text(), nullable=False,
            server_default='{"grants": [], "pending": []}'))
    if "migration_pending" not in cols:
        op.add_column("secret_refs", sa.Column(
            "migration_pending", sa.Boolean(), nullable=False,
            server_default=sa.false()))
    rows = bind.execute(sa.text(
        "SELECT name, kind FROM secret_refs")).fetchall()
    for name, kind in rows:
        grants = _derive_scope(bind, name) if kind == "runtime" else []
        bind.execute(sa.text(
            "UPDATE secret_refs SET scope_json = :s, "
            "migration_pending = 1 WHERE name = :n"),
            {"s": json.dumps({"grants": grants, "pending": []}),
             "n": name})


def downgrade() -> None:
    op.drop_column("secret_refs", "migration_pending")
    op.drop_column("secret_refs", "scope_json")
