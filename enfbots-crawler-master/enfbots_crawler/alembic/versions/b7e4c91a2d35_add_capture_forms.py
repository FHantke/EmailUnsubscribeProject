"""Add capture_forms for email-capture crawls

Revision ID: b7e4c91a2d35
Revises: 265e6a96f4ce
Create Date: 2026-10-09 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b7e4c91a2d35"
down_revision = "265e6a96f4ce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # update_database() runs create_all() before migrating, which may already have created it
    if sa.inspect(op.get_bind()).has_table("capture_forms"):
        return

    op.create_table(
        "capture_forms",
        sa.Column(
            "id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True
        ),
        sa.Column(
            "website_crawl_id",
            sa.Integer(),
            sa.ForeignKey("website_crawls.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("reject_reason", sa.String(), nullable=True),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("vendor_hint", sa.String(), nullable=True),
        sa.Column("frame_path", sa.String(), nullable=True),
        sa.Column("fields", sa.JSON(), nullable=True),
        sa.Column("captcha_type", sa.String(), nullable=True),
        sa.Column("captcha_visible", sa.Boolean(), nullable=True),
        sa.Column("signature", sa.String(40), nullable=False),
        sa.Column("html", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),  # pylint: disable=not-callable
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("capture_forms")
