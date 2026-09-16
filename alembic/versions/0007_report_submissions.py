"""report submissions

Revision ID: 0007_report_submissions
Revises: 0006_service_registrations
Create Date: 2026-09-16 16:00:00

A record of each round of results handed to the department (D21). Written by hand
and additive only, so nothing outside this table is touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0007_report_submissions'
down_revision: Union[str, Sequence[str], None] = '0006_service_registrations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'report_submissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hospital_id', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('people', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('summary', sa.JSON(), nullable=False),
        sa.Column('file_sha256', sa.String(length=64), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('submitted_by', sa.String(length=100), nullable=False),
        sa.Column('submitted_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_report_submissions_hospital_id'), 'report_submissions', ['hospital_id'])
    op.create_index(op.f('ix_report_submissions_year'), 'report_submissions', ['year'])


def downgrade() -> None:
    op.drop_index(op.f('ix_report_submissions_year'), table_name='report_submissions')
    op.drop_index(op.f('ix_report_submissions_hospital_id'), table_name='report_submissions')
    op.drop_table('report_submissions')
