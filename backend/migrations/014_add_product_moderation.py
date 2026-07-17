"""Add product moderation system — status, AI scoring, flags, moderation log.

Revision ID: 014
Revises: 013
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa

revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade():
    # Add moderation columns to product table
    op.add_column('product', sa.Column('status', sa.String(20), nullable=False, server_default='APPROVED'))
    op.add_column('product', sa.Column('ai_confidence_score', sa.Float, nullable=True))
    op.add_column('product', sa.Column('ai_moderation_result', sa.JSON, nullable=True))
    op.add_column('product', sa.Column('moderated_by', sa.String, sa.ForeignKey('admin_user.id', ondelete='SET NULL'), nullable=True))
    op.add_column('product', sa.Column('moderated_at', sa.DateTime, nullable=True))
    op.add_column('product', sa.Column('moderation_note', sa.Text, nullable=True))

    # Create product_flag table
    op.create_table(
        'product_flag',
        sa.Column('id', sa.String, primary_key=True),
        sa.Column('product_id', sa.String, sa.ForeignKey('product.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reported_by', sa.String, sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reason', sa.String(100), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('reviewed_by', sa.String, sa.ForeignKey('admin_user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime, nullable=True),
        sa.Column('admin_note', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # Create product_moderation_log table
    op.create_table(
        'product_moderation_log',
        sa.Column('id', sa.String, primary_key=True),
        sa.Column('product_id', sa.String, sa.ForeignKey('product.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('ai_score', sa.Float, nullable=True),
        sa.Column('ai_reasoning', sa.Text, nullable=True),
        sa.Column('performed_by', sa.String, sa.ForeignKey('admin_user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('note', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # Index for fast queue queries
    op.create_index('ix_product_status', 'product', ['status'])
    op.create_index('ix_product_flag_status', 'product_flag', ['status'])
    op.create_index('ix_product_flag_product_id', 'product_flag', ['product_id'])


def downgrade():
    op.drop_index('ix_product_flag_product_id')
    op.drop_index('ix_product_flag_status')
    op.drop_index('ix_product_status')
    op.drop_table('product_moderation_log')
    op.drop_table('product_flag')
    op.drop_column('product', 'moderation_note')
    op.drop_column('product', 'moderated_at')
    op.drop_column('product', 'moderated_by')
    op.drop_column('product', 'ai_moderation_result')
    op.drop_column('product', 'ai_confidence_score')
    op.drop_column('product', 'status')
