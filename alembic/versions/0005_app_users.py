"""app users

Revision ID: 0005_app_users
Revises: 0004_api_keys
Create Date: 2026-09-16 11:00:00

Accounts for the staff web pages (Env-Occ manual). Written by hand, so nothing
outside this table is touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0005_app_users'
down_revision: Union[str, Sequence[str], None] = '0004_api_keys'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('app_users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('surname', sa.String(length=200), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('hospital_id', sa.Integer(), nullable=True),
    sa.Column('license_no', sa.String(length=50), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_login_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )
    op.create_index(op.f('ix_app_users_email'), 'app_users', ['email'], unique=False)
    op.create_index(op.f('ix_app_users_hospital_id'), 'app_users', ['hospital_id'], unique=False)
    op.create_index(op.f('ix_app_users_role'), 'app_users', ['role'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_app_users_role'), table_name='app_users')
    op.drop_index(op.f('ix_app_users_hospital_id'), table_name='app_users')
    op.drop_index(op.f('ix_app_users_email'), table_name='app_users')
    op.drop_table('app_users')
