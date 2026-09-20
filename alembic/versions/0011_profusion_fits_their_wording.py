"""profusion is wide enough for the department's own wording

Revision ID: 0011_profusion_width
Revises: 0010_submission_round
Create Date: 2026-09-20 15:30:00

Found by running the department's own checkup_report_template through the
pipeline: it writes "no profusion" in this column, twelve characters into a
field of ten, so a real value from their own file could not be stored.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0011_profusion_width'
down_revision: Union[str, Sequence[str], None] = '0010_submission_round'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# v_employee_results_45 selects this column, and Postgres will not alter a type a
# view depends on. The view is dropped and rebuilt around the change; its
# definition is repeated here rather than imported, because a migration has to
# keep describing the shape it leaves behind even after 0008 is edited.
RESULT_COLUMNS = [
    "venous_blood_lead", "wbc", "hb", "hct", "plt", "neutrophil", "lymphocyte",
    "monocyte", "eosinophil", "basophil", "creatinine", "sgot_ast", "sgpt_alt",
    "alp", "tb", "db", "uric_acid", "chest_xray", "xray_comment", "profusion",
    "primary_lesion", "secondary_lesion", "rbc_che", "plasma_che_bche", "ekg",
    "ekg_comment", "bmi", "bp_systolic", "bp_diastolic", "pulse_rate",
    "spirometry_fvc_percent", "spirometry_fev1_percent", "spirometry_fvc",
    "spirometry_fev1", "spirometry_fev1_fvc", "spirometry_height",
    "hearing_ability", "hearing_comment", "far_vision_test", "far_vision_comment",
]

VIEW = """
    CREATE VIEW v_employee_results_45 AS
    SELECT c.id                              AS checkup_id,
           b.hospital_id                     AS hospital_id,
           c.source_file_id                  AS source_file_id,
           e.cid                             AS cid,
           e.first_name                      AS first_name,
           e.last_name                       AS last_name,
           d.name                            AS department_id,
           COALESCE(c.checkup_date, b.appoint_date) AS visit_date,
           {cols}
      FROM employee_checkups c
      JOIN employees e                ON e.id = c.employee_id
      JOIN departments d              ON d.id = e.department_pk
      JOIN employee_checkup_batches b ON b.id = c.checkup_batch_id
""".format(cols=", ".join(f"c.{c}" for c in RESULT_COLUMNS))


def upgrade() -> None:
    op.execute("DROP VIEW v_employee_results_45")
    op.alter_column("employee_checkups", "profusion",
                    existing_type=sa.String(10), type_=sa.String(50))
    op.execute(VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW v_employee_results_45")
    op.alter_column("employee_checkups", "profusion",
                    existing_type=sa.String(50), type_=sa.String(10))
    op.execute(VIEW)
