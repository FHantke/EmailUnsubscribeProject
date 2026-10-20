"""Add test_cases and jobs.test_case_id for study sign-ups

Revision ID: e5b8c1f04a27
Revises: d4a7f2c9e813
Create Date: 2026-10-20 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e5b8c1f04a27"
down_revision = "d4a7f2c9e813"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # update_database() runs create_all() first, which may already have created both
    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table("test_cases"):
        op.create_table(
            "test_cases",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("website_id", sa.Integer(), sa.ForeignKey("websites.id"), nullable=False),
            sa.Column(
                "capture_form_id",
                sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                sa.ForeignKey("capture_forms.id"),
                nullable=False,
            ),
            sa.Column("study_id", sa.String(), nullable=False),
            sa.Column("arm", sa.String(), nullable=False),
            sa.Column("alias", sa.String(), nullable=False, unique=True),
            sa.Column("persona", sa.String(), nullable=False),
            sa.Column("selection_reason", sa.String(), nullable=True),
            sa.Column("submit_status", sa.String(), nullable=False),
            sa.Column("submit_detail", sa.JSON(), nullable=True),
            sa.Column("submit_page_url", sa.String(), nullable=True),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("confirm_status", sa.String(), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),  # pylint: disable=not-callable
                nullable=False,
            ),
        )

    if "test_case_id" not in {c["name"] for c in inspector.get_columns("jobs")}:
        op.add_column("jobs", sa.Column("test_case_id", sa.Integer(), nullable=True))
        # SQLite cannot add a constraint to an existing table; the column works without it
        if op.get_bind().dialect.name != "sqlite":
            op.create_foreign_key(
                "jobs_test_case_id_fkey", "jobs", "test_cases", ["test_case_id"], ["id"]
            )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("jobs_test_case_id_fkey", "jobs", type_="foreignkey")
    op.drop_column("jobs", "test_case_id")
    op.drop_table("test_cases")
