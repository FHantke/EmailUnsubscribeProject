"""Implement detection of US privacy policies

Revision ID: 47f4b6846ed8
Revises: 18853c64f5ff
Create Date: 2023-05-18 12:55:56.198719

"""
from alembic import op
from sqlalchemy import Column, Enum
from sqlalchemy import schema
import sqlalchemy as sa

from enfbots_crawler.database import CrawlToUSPrivacyNotice, DBWebsiteCrawl
from enfbots_crawler.database import ConsiderationBasis, CREATE_OR_REPLACE_best_us_pn_urls_kw

# revision identifiers, used by Alembic.
revision = '47f4b6846ed8'
down_revision = '18853c64f5ff'
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = CrawlToUSPrivacyNotice.__table__.columns.values()

    # Due to: https://github.com/sqlalchemy/alembic/issues/278
    # I have to create this column separately
    found = False
    for c in CrawlToUSPrivacyNotice.__table__.columns.values():
        if c.name == CrawlToUSPrivacyNotice.consideration_basis.name:
            found = True
            x = c
    if not found:
        raise Exception("Column not found; Is the alembic_version wrong? Or is the database changed?")

    columns.remove(x)

    schema_item = [ schema.Column(col.name, col.type) for col in columns]

    op.create_table(CrawlToUSPrivacyNotice.__tablename__, *schema_item)

    # Add column with check_first set to true for the Enum
    op.add_column(CrawlToUSPrivacyNotice.__tablename__, Column(CrawlToUSPrivacyNotice.consideration_basis.name ,Enum(ConsiderationBasis, check_first=True)))

    op.execute(CREATE_OR_REPLACE_best_us_pn_urls_kw)


def downgrade() -> None:
    raise Exception("Not supported")
