"""Add capture_forms.visible for pop-up triggers

Revision ID: d4a7f2c9e813
Revises: b7e4c91a2d35
Create Date: 2026-10-09 18:30:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d4a7f2c9e813"
down_revision = "b7e4c91a2d35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # update_database() runs create_all() first, which creates a missing capture_forms table
    # with this column already in it
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("capture_forms")}
    if "visible" in columns:
        return
    op.add_column("capture_forms", sa.Column("visible", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("capture_forms", "visible")
