"""Add websites.url unique constraint
 
Revision ID: 48b1cc55755d
Revises: fb6d39aa8d87
Create Date: 2024-02-12 15:34:37.231531
 
"""

from alembic import op
from sqlalchemy import text
from tqdm import tqdm

from enfbots_crawler.database import CREATE_WEBSITES_URL_UNIQUE_CONSTRAINT

# revision identifiers, used by Alembic.
revision = "48b1cc55755d"
down_revision = "fb6d39aa8d87"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # get all duplicated website_ids

    # pylint: disable=no-member
    conn = op.get_bind()
    res = conn.execute(text("SELECT url FROM websites GROUP BY url HAVING count(url) > 1"))

    # for each duplicate set all others to the first occurence
    for x in tqdm(res.fetchall()):
        duplicates = conn.execute(
            text("SELECT id, url FROM websites where url = :url").bindparams(url=x[0])
        ).fetchall()

        assert len(duplicates) > 1

        new_id = duplicates[0][0]
        for d in duplicates[1:]:
            conn.execute(
                text("UPDATE jobs SET website_id = :new_id WHERE website_id = :old_id").bindparams(
                    old_id=d[0], new_id=new_id
                )
            )
            conn.execute(
                text(
                    "UPDATE website_crawls SET website_id = :new_id WHERE website_id = :old_id"
                ).bindparams(old_id=d[0], new_id=new_id)
            )

            # delete website
            conn.execute(text("DELETE FROM websites WHERE id = :id").bindparams(id=d[0]))

    op.execute(CREATE_WEBSITES_URL_UNIQUE_CONSTRAINT)


def downgrade() -> None:
    raise RuntimeError("Not supported")
