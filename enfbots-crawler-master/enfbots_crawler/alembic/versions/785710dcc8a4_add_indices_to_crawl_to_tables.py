"""Add indices to crawl_to_{privacy_policy,terms_and_conditions} for faster queries to the views best_{pp,tc}_urls_kw

Revision ID: 785710dcc8a4
Revises: c1619daa5159
Create Date: 2023-11-30 16:26:23.467717

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '785710dcc8a4'
down_revision = 'c1619daa5159'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE INDEX IF NOT EXISTS pp_kw_score_index
        ON crawl_to_privacy_policy USING btree
        (pp_kw_score ASC NULLS LAST) """)
    
    op.execute("""CREATE INDEX IF NOT EXISTS tc_kw_score_index
        ON crawl_to_terms_and_conditions USING btree
        (tc_kw_score ASC NULLS LAST)""")


def downgrade() -> None:
    raise Exception("Not supported")
