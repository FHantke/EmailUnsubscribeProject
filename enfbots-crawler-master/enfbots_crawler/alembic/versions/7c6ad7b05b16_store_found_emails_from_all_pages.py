"""Store found emails from all pages

Revision ID: 7c6ad7b05b16
Revises: 47f4b6846ed8
Create Date: 2023-05-25 20:48:56.556916

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import Column, JSON

from enfbots_crawler.database import DBWebsiteCrawl

# revision identifiers, used by Alembic.
revision = '7c6ad7b05b16'
down_revision = '47f4b6846ed8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(DBWebsiteCrawl.__tablename__, Column(DBWebsiteCrawl.found_emails.name, JSON))
    pass


def downgrade() -> None:
    raise Exception("Not supported")
