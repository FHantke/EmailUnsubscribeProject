"""Update ConsiderationBasis enum in the database

Revision ID: 9332de89ae2f
Revises: 4a6904d206ec
Create Date: 2023-08-21 23:36:08.004369

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9332de89ae2f'
down_revision = '4a6904d206ec'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE considerationbasis ADD VALUE 'POPULAR'")
    op.execute("ALTER TYPE considerationbasis ADD VALUE 'POPULAR_CLASSIFIER'")


def downgrade() -> None:
    raise Exception("Not supported")
