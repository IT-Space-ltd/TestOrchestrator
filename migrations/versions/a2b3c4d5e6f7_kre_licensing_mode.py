"""KRE licensing modes: runtime_connections.licensing_mode /
license_refs / license_server_url

Revision ID: a2b3c4d5e6f7
Revises: z8a9b0c1d2e3
Create Date: 2026-11-25

Additive only. Existing runtimes keep licensing_mode 'online' —
their behaviour is byte-identical to the pre-migration gate
(credential_ref or credential_file required; -apiKey emitted).
"""
from alembic import op
import sqlalchemy as sa

revision = "a2b3c4d5e6f7"
down_revision = "z8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as _inspect
    bind = op.get_bind()
    cols = {c["name"] for c in
            _inspect(bind).get_columns("runtime_connections")}
    if "licensing_mode" not in cols:
        op.add_column("runtime_connections", sa.Column(
            "licensing_mode", sa.String(16), nullable=False,
            server_default="online"))
    if "license_refs" not in cols:
        op.add_column("runtime_connections", sa.Column(
            "license_refs", sa.Text(), nullable=False,
            server_default="[]"))
    if "license_server_url" not in cols:
        op.add_column("runtime_connections", sa.Column(
            "license_server_url", sa.String(512), nullable=False,
            server_default=""))


def downgrade() -> None:
    op.drop_column("runtime_connections", "license_server_url")
    op.drop_column("runtime_connections", "license_refs")
    op.drop_column("runtime_connections", "licensing_mode")
