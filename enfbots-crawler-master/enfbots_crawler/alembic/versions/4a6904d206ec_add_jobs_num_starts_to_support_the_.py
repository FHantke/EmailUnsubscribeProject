"""Add jobs.num_starts to support the limitation of the amount of tries for a job

Revision ID: 4a6904d206ec
Revises: c5558de8a152
Create Date: 2023-08-08 10:19:53.152159

"""

from alembic import op
from sqlalchemy import Column, Integer

from enfbots_crawler.database import DBJob


# revision identifiers, used by Alembic.
revision = "4a6904d206ec"
down_revision = "c5558de8a152"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(DBJob.__tablename__, Column(DBJob.num_starts.name, Integer, default=0))


def downgrade() -> None:
    raise RuntimeError("Not supported")
