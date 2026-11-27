"""projects: per-project retention policy overrides

Revision ID: m1a2b3c4d5e6
Revises: l1a2b3c4d5e6
"""
from alembic import op
import sqlalchemy as sa

revision = "m1a2b3c4d5e6"
down_revision = "l1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("projects") as b:
        b.add_column(sa.Column("retention_json", sa.Text,
                               nullable=False, server_default="{}"))


def downgrade():
    with op.batch_alter_table("projects") as b:
        b.drop_column("retention_json")
