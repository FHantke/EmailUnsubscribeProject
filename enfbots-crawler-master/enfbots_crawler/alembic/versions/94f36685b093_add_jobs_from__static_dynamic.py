"""Add jobs.from_{static,dynamic}

Revision ID: 94f36685b093
Revises: f320bc3256aa
Create Date: 2024-01-13 12:13:50.674148

"""
from typing import List, cast
import json
from tqdm import tqdm

from alembic import op
from sqlalchemy import Column, Boolean

from sqlalchemy import select, text

from enfbots_crawler.database import DBJob

# revision identifiers, used by Alembic.
revision = "94f36685b093"
down_revision = "f320bc3256aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(DBJob.__tablename__, Column(DBJob.from_dynamic.name, Boolean, nullable=True))
    op.add_column(DBJob.__tablename__, Column(DBJob.from_static.name, Boolean, nullable=True))

    conn = op.get_bind()
    jobs: List[DBJob] = cast(List[DBJob], list(conn.execute(select(DBJob)).all()))

    for j in tqdm(jobs, desc="Migrating jobs"):
        if j.other and "from_list" in j.other and j.other["from_list"] == 1:
            d = j.other
            del d["from_list"]
            if len(d) == 0:
                op.execute(text(f"UPDATE jobs SET other = NULL WHERE id = {j.id}"))
            else:
                op.execute(text(f"UPDATE jobs SET other = '{json.dumps(d)}' WHERE id = {j.id}"))
            op.execute(text(f"UPDATE jobs SET from_static = True WHERE id = {j.id}"))


def downgrade() -> None:
    raise RuntimeError("Not supported")
