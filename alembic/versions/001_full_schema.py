"""full_schema

Revision ID: 001_full_schema
Revises: 
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '001_full_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bookings',
        sa.Column('booking_id', sa.String(length=64), nullable=False),
        sa.Column('workflow_id', sa.String(length=128), nullable=False),
        sa.Column('idempotency_key', sa.String(length=128), nullable=False),
        sa.Column('supplier_id', sa.String(length=32), nullable=False),
        sa.Column('property_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('supplier_reservation_id', sa.String(length=128), nullable=True),
        sa.Column('total_price', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('guest_name', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('booking_id'),
        sa.UniqueConstraint('idempotency_key')
    )
    op.create_index(op.f('ix_bookings_booking_id'), 'bookings', ['booking_id'], unique=False)
    op.create_index(op.f('ix_bookings_idempotency_key'), 'bookings', ['idempotency_key'], unique=True)
    op.create_index(op.f('ix_bookings_workflow_id'), 'bookings', ['workflow_id'], unique=False)

    op.create_table(
        'search_requests',
        sa.Column('request_id', sa.String(length=64), nullable=False),
        sa.Column('destination', sa.String(length=128), nullable=False),
        sa.Column('check_in', sa.Date(), nullable=False),
        sa.Column('check_out', sa.Date(), nullable=False),
        sa.Column('guests', sa.Integer(), nullable=False),
        sa.Column('rooms', sa.Integer(), nullable=False),
        sa.Column('suppliers_queried', sa.JSON(), nullable=False),
        sa.Column('suppliers_failed', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('request_id')
    )
    op.create_index(op.f('ix_search_requests_request_id'), 'search_requests', ['request_id'], unique=False)

    op.create_table(
        'normalized_offers',
        sa.Column('offer_id', sa.String(length=64), nullable=False),
        sa.Column('request_id', sa.String(length=64), nullable=False),
        sa.Column('supplier_id', sa.String(length=32), nullable=False),
        sa.Column('property_id', sa.String(length=64), nullable=False),
        sa.Column('property_name', sa.String(length=128), nullable=False),
        sa.Column('location', sa.String(length=128), nullable=False),
        sa.Column('room_type', sa.String(length=64), nullable=False),
        sa.Column('check_in_date', sa.Date(), nullable=False),
        sa.Column('check_out_date', sa.Date(), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('base_price', sa.Float(), nullable=False),
        sa.Column('taxes_and_fees', sa.Float(), nullable=False),
        sa.Column('total_price', sa.Float(), nullable=False),
        sa.Column('cancellation_policy', sa.String(length=256), nullable=False),
        sa.Column('availability_status', sa.String(length=32), nullable=False),
        sa.Column('rank_score', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['request_id'], ['search_requests.request_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('offer_id')
    )
    op.create_index(op.f('ix_normalized_offers_offer_id'), 'normalized_offers', ['offer_id'], unique=False)
    op.create_index(op.f('ix_normalized_offers_request_id'), 'normalized_offers', ['request_id'], unique=False)

    op.create_table(
        'supplier_references',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('booking_id', sa.String(length=64), nullable=False),
        sa.Column('supplier_id', sa.String(length=32), nullable=False),
        sa.Column('supplier_reservation_id', sa.String(length=128), nullable=False),
        sa.Column('raw_supplier_response', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['booking_id'], ['bookings.booking_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_supplier_references_booking_id'), 'supplier_references', ['booking_id'], unique=False)

    op.create_table(
        'booking_status_history',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('booking_id', sa.String(length=64), nullable=False),
        sa.Column('previous_status', sa.String(length=32), nullable=True),
        sa.Column('new_status', sa.String(length=32), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['booking_id'], ['bookings.booking_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_booking_status_history_booking_id'), 'booking_status_history', ['booking_id'], unique=False)

    op.create_table(
        'failure_log',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('context', sa.String(length=64), nullable=False),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('booking_id', sa.String(length=64), nullable=True),
        sa.Column('supplier_id', sa.String(length=32), nullable=True),
        sa.Column('error_type', sa.String(length=128), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=False),
        sa.Column('retry_attempt_number', sa.Integer(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_failure_log_booking_id'), 'failure_log', ['booking_id'], unique=False)
    op.create_index(op.f('ix_failure_log_request_id'), 'failure_log', ['request_id'], unique=False)


def downgrade() -> None:
    op.drop_table('failure_log')
    op.drop_table('booking_status_history')
    op.drop_table('supplier_references')
    op.drop_table('normalized_offers')
    op.drop_table('search_requests')
    op.drop_table('bookings')
