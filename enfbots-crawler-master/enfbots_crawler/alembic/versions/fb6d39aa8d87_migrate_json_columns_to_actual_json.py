"""Migrate JSON columns to actual JSON

Before the columns were a JSON string. Convert them to a proper JSON dictionary.

Revision ID: fb6d39aa8d87
Revises: 94f36685b093
Create Date: 2024-01-25 06:53:08.886753

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import select, text
import json
from typing import Dict
from tqdm import tqdm

from enfbots_crawler import DBJob

# revision identifiers, used by Alembic.
revision = 'fb6d39aa8d87'
down_revision = '94f36685b093'
branch_labels = None
depends_on = None

def jsonify_column(column: str, table: str) -> None:
    connection = op.get_bind()

    count = connection.execute(text(f'select count(*) from {table}')).scalar()

    if count is None:
        raise RuntimeError(f"Unable to get amount of rows from {table}.{column}")
    total = int(count)

    for row in tqdm(connection.execute(text(f'select id, {column} from {table}')), desc=f"Updating table {table}.{column} JSON values", total=total):
        id = row[0]
        value = row[1]
 
        if not isinstance(value, Dict) and value is not None:
            statement = text(f'UPDATE {table} SET {column} = :value WHERE id = {id}')
            statement = statement.bindparams(value=value)
            connection.execute(statement)


def upgrade() -> None:
    jsonify_column('additional_crux_ranks', 'jobs')
    jsonify_column('other', 'jobs')
    jsonify_column('found_emails', 'website_crawls')
    jsonify_column('states', 'website_crawls')
    jsonify_column('urls', 'forms')
    jsonify_column('states', 'forms')
    jsonify_column('other', 'mails')
    jsonify_column('other', 'form_legal_labels')
    jsonify_column('other', 'violations')




def downgrade() -> None:
    raise RuntimeError("Not supported")
