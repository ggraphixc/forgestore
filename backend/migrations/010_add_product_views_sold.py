"""Add views_count and sold_count to product table."""

from alembic import op
import sqlalchemy as sa

revision = "010_add_product_views_sold"
down_revision = "009_add_ai_chat_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("product", sa.Column("views_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("product", sa.Column("sold_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("product", "sold_count")
    op.drop_column("product", "views_count")
