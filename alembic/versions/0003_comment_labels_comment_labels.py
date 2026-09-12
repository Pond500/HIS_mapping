"""comment labels

Revision ID: 0003_comment_labels
Revises: 0002_seed
Create Date: 2026-09-12 22:52:35.950402

Only the comment_labels table. The first autogenerate of this revision also
proposed dropping LangGraph's checkpoint* tables (they live in the same DB but
are not in our metadata); that was removed here, and alembic/env.py now
filters such tables out (include_object).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0003_comment_labels'
down_revision: Union[str, Sequence[str], None] = '0002_seed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('comment_labels',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('column', sa.String(length=100), nullable=False),
    sa.Column('text_norm', sa.String(length=500), nullable=False),
    sa.Column('value', sa.SmallInteger(), nullable=False),
    sa.Column('origin', sa.String(length=20), nullable=False),
    sa.Column('approved_by', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('column', 'text_norm')
    )


def downgrade() -> None:
    op.drop_table('comment_labels')
