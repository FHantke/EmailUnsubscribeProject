"""Improve best_{pp,tc}_urls by also including cached URLs

Revision ID: c1619daa5159
Revises: e2134eda8d83
Create Date: 2023-11-13 15:46:21.144346

"""
from alembic import op
import sqlalchemy as sa

from enfbots_crawler.database import create_views


# revision identifiers, used by Alembic.
revision = 'c1619daa5159'
down_revision = 'e2134eda8d83'
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_views()


def downgrade() -> None:
    raise Exception("Not supported")
