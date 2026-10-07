"""Rename columns

Revision ID: e8d86d9dedf3
Revises: e126894e5b02
Create Date: 2023-05-17 16:40:43.868841

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e8d86d9dedf3"
down_revision = "e126894e5b02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("crawl_to_privacy_policy", "crawl_id", new_column_name="website_crawl_id")
    op.alter_column("crawl_to_terms_and_conditions", "crawl_id", new_column_name="website_crawl_id")


def downgrade() -> None:
    raise Exception("Not supported")
