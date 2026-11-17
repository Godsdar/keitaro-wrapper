"""initial tables

Revision ID: e54f8c4fbef1
Revises: 
Create Date: 2026-11-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e54f8c4fbef1'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('campaigns',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('keitaro_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('alias', sa.String(length=64), nullable=True),
    sa.Column('geo', sa.String(length=255), nullable=True),
    sa.Column('offer_id', sa.Integer(), nullable=True),
    sa.Column('domain_id', sa.Integer(), nullable=True),
    sa.Column('group_id', sa.Integer(), nullable=True),
    sa.Column('traffic_source_id', sa.Integer(), nullable=True),
    sa.Column('created_by_wrapper', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_campaigns_keitaro_id'), ['keitaro_id'], unique=True)

    op.create_table('streams',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('keitaro_id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('type', sa.String(length=32), nullable=True),
    sa.Column('schema', sa.String(length=32), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('state', sa.String(length=32), nullable=True),
    sa.Column('pushed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('streams', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_streams_keitaro_id'), ['keitaro_id'], unique=True)

    op.create_table('stream_offers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('stream_id', sa.Integer(), nullable=False),
    sa.Column('offer_id', sa.Integer(), nullable=False),
    sa.Column('offer_name', sa.String(length=255), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('share', sa.Integer(), nullable=False),
    sa.Column('pinned', sa.Boolean(), nullable=False),
    sa.Column('pub_status', sa.String(length=16), nullable=True),
    sa.Column('pub_share', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['stream_id'], ['streams.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stream_id', 'offer_id', name='uq_stream_offer')
    )
    with op.batch_alter_table('stream_offers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stream_offers_stream_id'), ['stream_id'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('stream_offers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_stream_offers_stream_id'))

    op.drop_table('stream_offers')
    with op.batch_alter_table('streams', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_streams_keitaro_id'))

    op.drop_table('streams')
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_campaigns_keitaro_id'))

    op.drop_table('campaigns')
