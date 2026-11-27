"""runtime_connections: framework-adapted config + readiness state

Revision ID: l1a2b3c4d5e6
Revises: j1a2b3c4d5e6
"""
from alembic import op
import sqlalchemy as sa

revision = "l1a2b3c4d5e6"
down_revision = "j1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("runtime_connections") as b:
        b.add_column(sa.Column("config_json", sa.Text, nullable=False,
                               server_default="{}"))
        b.add_column(sa.Column("readiness_state", sa.String(32),
                               nullable=False,
                               server_default="not-checked"))


def downgrade():
    with op.batch_alter_table("runtime_connections") as b:
        b.drop_column("readiness_state")
        b.drop_column("config_json")
