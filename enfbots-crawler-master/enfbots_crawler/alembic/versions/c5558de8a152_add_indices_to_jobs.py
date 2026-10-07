"""Add indices to jobs

Revision ID: c5558de8a152
Revises: 7c6ad7b05b16
Create Date: 2023-06-27 23:02:45.099386

"""

from alembic import op

from enfbots_crawler.database import (
    CREATE_JOBS_CREATED_AT_INDEX,
    CREATE_JOBS_STARTED_AT_INDEX,
    CREATE_EMAILS_WEBSITE_CRAWL_INDEX,
    CREATE_WEBSITES_URL_INDEX,
)

# revision identifiers, used by Alembic.
revision = "c5558de8a152"
down_revision = "7c6ad7b05b16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pylint: disable=no-member
    op.execute(CREATE_JOBS_CREATED_AT_INDEX)
    op.execute(CREATE_JOBS_STARTED_AT_INDEX)
    op.execute(CREATE_EMAILS_WEBSITE_CRAWL_INDEX)
    op.execute(CREATE_WEBSITES_URL_INDEX)


def downgrade() -> None:
    raise RuntimeError("Not supported")
