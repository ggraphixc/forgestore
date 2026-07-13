"""Add video_url column to product table."""

from alembic import op
import sqlalchemy as sa

revision = "011_add_product_video_url"
down_revision = "010_add_product_views_sold"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("product", sa.Column("video_url", sa.String(500), nullable=True))


def downgrade():
    op.drop_column("product", "video_url")
