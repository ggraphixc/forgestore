"""Create bulk_order table."""

from alembic import op
import sqlalchemy as sa

revision = "012_add_bulk_order"
down_revision = "011_add_product_video_url"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bulk_order",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("customer_id", sa.String(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("product_id", sa.String(), sa.ForeignKey("product.id", ondelete="CASCADE"), nullable=False),
        sa.Column("retailer_id", sa.String(), sa.ForeignKey("retailer.id", ondelete="SET NULL"), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("total_price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("customer_name", sa.String(255), nullable=True),
        sa.Column("customer_email", sa.String(255), nullable=True),
        sa.Column("customer_phone", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("vendor_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("bulk_order")
