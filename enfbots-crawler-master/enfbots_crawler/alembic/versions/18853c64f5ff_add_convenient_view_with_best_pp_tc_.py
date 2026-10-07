"""Add convenient view with best PP/TC links

Revision ID: 18853c64f5ff
Revises: e8d86d9dedf3
Create Date: 2023-05-17 16:56:28.143353

"""
from alembic import op
import sqlalchemy as sa

from enfbots_crawler.config import Config
from enfbots_crawler.database import (
    CREATE_OR_REPLACE_best_pp_urls_kw,
    CREATE_OR_REPLACE_best_tc_urls_kw,
)


# revision identifiers, used by Alembic.
revision = '18853c64f5ff'
down_revision = 'e8d86d9dedf3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(CREATE_OR_REPLACE_best_pp_urls_kw)
    op.execute(CREATE_OR_REPLACE_best_tc_urls_kw)


def downgrade() -> None:
    raise Exception("Not supported")
