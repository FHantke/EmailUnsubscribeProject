"""Add TC probability

Revision ID: 265e6a96f4ce
Revises: d42403b400cd
Create Date: 2024-05-25 16:12:37.826638

"""

from alembic import op
from sqlalchemy import Float, Column
import sqlalchemy as sa

from enfbots_crawler.database import CrawlToTermsAndConditions

# revision identifiers, used by Alembic.
revision = "265e6a96f4ce"
down_revision = "d42403b400cd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add column
    op.add_column(
        CrawlToTermsAndConditions.__tablename__,
        Column(CrawlToTermsAndConditions.tc_probability.name, Float(precision=16)),
    )


def downgrade() -> None:
    raise RuntimeError("Not supported")
