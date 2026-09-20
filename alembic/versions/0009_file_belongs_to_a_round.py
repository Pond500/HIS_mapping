"""a file belongs to a checkup round, or to a company's register

Revision ID: 0009_file_belongs_to_a_round
Revises: 0008_ddc_schema
Create Date: 2026-09-20 13:00:00

D23. An uploaded file is no longer self-contained. A results file only means
something inside a round — that is where its date comes from — and a register
file only means something inside a workplace. Both are chosen in the upload
dialog before the file is picked, the way the department's manual has it.

Nullable, because files uploaded before this point had neither.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0009_file_belongs_to_a_round'
down_revision: Union[str, Sequence[str], None] = '0008_ddc_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("source_files", sa.Column(
        "field_set", sa.String(20), nullable=False, server_default="result"))
    op.add_column("source_files", sa.Column(
        "checkup_batch_id", sa.Integer(),
        sa.ForeignKey("employee_checkup_batches.id"), nullable=True))
    op.add_column("source_files", sa.Column(
        "company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True))
    op.create_index("ix_source_files_checkup_batch_id", "source_files", ["checkup_batch_id"])
    op.create_index("ix_source_files_company_id", "source_files", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_source_files_company_id", "source_files")
    op.drop_index("ix_source_files_checkup_batch_id", "source_files")
    op.drop_column("source_files", "company_id")
    op.drop_column("source_files", "checkup_batch_id")
    op.drop_column("source_files", "field_set")
