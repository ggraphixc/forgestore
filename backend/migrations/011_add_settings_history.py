"""Add settings_history table for tracking settings changes."""

from alembic import op
import sqlalchemy as sa

revision = "011_add_settings_history"
down_revision = "010_add_product_views_sold"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "settings_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("setting_key", sa.String(255), nullable=False, index=True),
        sa.Column("old_value", sa.Text, nullable=True),
        sa.Column("new_value", sa.Text, nullable=True),
        sa.Column("changed_by_admin_id", sa.String(36), sa.ForeignKey("admin_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("changed_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_settings_history_changed_at", "settings_history", ["changed_at"])


def downgrade():
    op.drop_index("ix_settings_history_changed_at", table_name="settings_history")
    op.drop_table("settings_history")
