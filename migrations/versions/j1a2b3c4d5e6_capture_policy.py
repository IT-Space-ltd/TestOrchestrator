"""projects.capture_policy_json — artifact capture permissions

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
"""
from alembic import op
import sqlalchemy as sa

revision = "j1a2b3c4d5e6"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("projects") as b:
        b.add_column(sa.Column("capture_policy_json", sa.Text,
                               nullable=False, server_default="{}"))


def downgrade():
    with op.batch_alter_table("projects") as b:
        b.drop_column("capture_policy_json")
