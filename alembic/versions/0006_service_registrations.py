"""service registrations

Revision ID: 0006_service_registrations
Revises: 0005_app_users
Create Date: 2026-09-16 13:00:00

Applications to register a medical service unit (Env-Occ manual: ขึ้นทะเบียนหน่วยบริการ).
Written by hand, so nothing outside this table is touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0006_service_registrations'
down_revision: Union[str, Sequence[str], None] = '0005_app_users'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('service_registrations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('hospital_id', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('stage', sa.Integer(), nullable=False),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('documents', sa.JSON(), nullable=False),
    sa.Column('review_notes', sa.JSON(), nullable=False),
    sa.Column('delivery', sa.JSON(), nullable=False),
    sa.Column('certificate_path', sa.String(length=1000), nullable=True),
    sa.Column('certificate_downloaded', sa.Boolean(), nullable=False),
    sa.Column('submitted_at', sa.DateTime(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.Column('approved_at', sa.DateTime(), nullable=True),
    sa.Column('issued_at', sa.DateTime(), nullable=True),
    sa.Column('expires_on', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['app_users.id'], ),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_service_registrations_hospital_id'), 'service_registrations', ['hospital_id'], unique=False)
    op.create_index(op.f('ix_service_registrations_status'), 'service_registrations', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_service_registrations_status'), table_name='service_registrations')
    op.drop_index(op.f('ix_service_registrations_hospital_id'), table_name='service_registrations')
    op.drop_table('service_registrations')
