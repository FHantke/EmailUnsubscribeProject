"""Add TOO_SHORT_TEXT

Revision ID: d42403b400cd
Revises: 1acae6d8ef17
Create Date: 2024-05-07 12:19:56.841135

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d42403b400cd"
down_revision = "1acae6d8ef17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE considerationbasis ADD VALUE 'TOO_SHORT_TEXT'")


def downgrade() -> None:
    raise RuntimeError("Not supported")
