"""Update database views of PP, TC and US-PP urls

Revision ID: 5c746ec53574
Revises: a54b597a6341
Create Date: 2023-12-05 00:04:59.019762

"""
from alembic import op
import sqlalchemy as sa
from enfbots_crawler.database import (
    CREATE_OR_REPLACE_best_pp_urls_kw,
    CREATE_OR_REPLACE_best_tc_urls_kw,
    CREATE_OR_REPLACE_best_us_pn_urls_kw
)


# revision identifiers, used by Alembic.
revision = '5c746ec53574'
down_revision = 'a54b597a6341'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(CREATE_OR_REPLACE_best_pp_urls_kw)
    op.execute(CREATE_OR_REPLACE_best_tc_urls_kw)
    op.execute(CREATE_OR_REPLACE_best_us_pn_urls_kw)


def downgrade() -> None:
    raise Exception("Not supported")
