"""Add additional crux ranks to jobs table

Revision ID: f320bc3256aa
Revises: 5c746ec53574
Create Date: 2023-12-22 18:18:07.985466

"""
from alembic import op
import sqlalchemy as sa

from enfbots_crawler.database import DBJob

# revision identifiers, used by Alembic.
revision = 'f320bc3256aa'
down_revision = '5c746ec53574'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", DBJob.additional_crux_ranks) # type: ignore


def downgrade() -> None:
    raise Exception("Not supported")
