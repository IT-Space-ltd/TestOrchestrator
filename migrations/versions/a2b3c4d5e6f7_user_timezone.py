"""Per-user display time zone: users.timezone (IANA name, UTC default)

Revision ID: a2b3c4d5e6f7
Revises: a9b0c1d2e3f4
Create Date: 2026-11-22

Additive only.

- users.timezone: IANA identifier for display localization. The
  server default "UTC" migrates every existing user to the behaviour
  they already see; the preference never alters stored instants.
"""
from alembic import op
import sqlalchemy as sa

revision = "a2b3c4d5e6f7"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as _inspect
    cols = {c["name"] for c in
            _inspect(op.get_bind()).get_columns("users")}
    if "timezone" not in cols:
        op.add_column("users", sa.Column(
            "timezone", sa.String(64), nullable=False,
            server_default="UTC"))


def downgrade() -> None:
    from sqlalchemy import inspect as _inspect
    cols = {c["name"] for c in
            _inspect(op.get_bind()).get_columns("users")}
    if "timezone" in cols:
        op.drop_column("users", "timezone")
