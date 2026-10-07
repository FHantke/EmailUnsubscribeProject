"""Add ConsiderationBasis.CACHED

Revision ID: e2134eda8d83
Revises: 9332de89ae2f
Create Date: 2023-11-12 21:21:14.165877

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e2134eda8d83'
down_revision = '9332de89ae2f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE considerationbasis ADD VALUE 'CACHED'")
    op.execute("COMMIT")


def downgrade() -> None:
    raise Exception("Not supported")
