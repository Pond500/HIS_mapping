"""a hand-over is one checkup round

Revision ID: 0010_submission_round
Revises: 0009_file_belongs_to_a_round
Create Date: 2026-09-20 15:00:00

D23. A submission used to be "this hospital, this year". The department receives
one checkup round at a time, and its own tables are keyed that way, so that is
what a hand-over records.

Nullable: submissions made before this point were not rounds and cannot be
retrofitted into one without inventing which round they were.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0010_submission_round'
down_revision: Union[str, Sequence[str], None] = '0009_file_belongs_to_a_round'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("report_submissions", sa.Column(
        "checkup_batch_id", sa.Integer(),
        sa.ForeignKey("employee_checkup_batches.id"), nullable=True))
    op.create_index("ix_report_submissions_checkup_batch_id",
                    "report_submissions", ["checkup_batch_id"])


def downgrade() -> None:
    op.drop_index("ix_report_submissions_checkup_batch_id", "report_submissions")
    op.drop_column("report_submissions", "checkup_batch_id")
