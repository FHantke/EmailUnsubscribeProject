"""Add is_insecure to forms

Revision ID: 1acae6d8ef17
Revises: 48b1cc55755d
Create Date: 2024-02-22 12:59:50.515564

"""

from alembic import op
import sqlalchemy as sa

from enfbots_crawler.database import DBForm

# revision identifiers, used by Alembic.
revision = "1acae6d8ef17"
down_revision = "48b1cc55755d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        DBForm.__tablename__, sa.Column(DBForm.is_insecure.name, sa.Boolean, default=None)
    )


def downgrade() -> None:
    raise RuntimeError("Not supported")
