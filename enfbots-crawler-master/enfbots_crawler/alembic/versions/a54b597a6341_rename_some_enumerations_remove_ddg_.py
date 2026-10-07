"""Rename some enumerations (remove DDG from name)

Revision ID: a54b597a6341
Revises: 785710dcc8a4
Create Date: 2023-12-19 23:19:14.787375

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a54b597a6341'
down_revision = '785710dcc8a4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE considerationbasis RENAME VALUE 'DDG_SEARCH_CLASSIFIER' TO 'SEARCH_CLASSIFIER'")
    op.execute("ALTER TYPE considerationbasis RENAME VALUE 'KEYWORD_MATCHING_DDG' TO 'KEYWORD_MATCHING_SEARCH'")
    op.execute("ALTER TYPE considerationbasis RENAME VALUE 'DDG_SEARCH' TO 'SEARCH'")


def downgrade() -> None:
    raise Exception("Not supported")
