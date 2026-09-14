"""api keys

Revision ID: 0004_api_keys
Revises: 0003_comment_labels
Create Date: 2026-09-14 12:00:00

API keys for the external API (D19), and which key sent each file.
Written by hand (no autogenerate), so nothing outside these two changes is touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0004_api_keys'
down_revision: Union[str, Sequence[str], None] = '0003_comment_labels'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('api_keys',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('hospital_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('prefix', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key_hash')
    )
    op.create_index(op.f('ix_api_keys_hospital_id'), 'api_keys', ['hospital_id'], unique=False)
    op.add_column('source_files', sa.Column('api_key_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'source_files', 'api_keys', ['api_key_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('source_files_api_key_id_fkey', 'source_files', type_='foreignkey')
    op.drop_column('source_files', 'api_key_id')
    op.drop_index(op.f('ix_api_keys_hospital_id'), table_name='api_keys')
    op.drop_table('api_keys')
