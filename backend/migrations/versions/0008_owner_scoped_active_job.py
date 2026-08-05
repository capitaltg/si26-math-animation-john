"""scope the active-job constraint to the owning session

Revision ID: 0008_owner_scoped_active_job
Revises: 0007_template_ownership

0007 made an enabled template version per-owner but left the active-job
constraint global, so one teacher's in-flight private build refused every other
session's request for the same problem shape -- and that refusal is terminal in
the teacher's band, which offered no way back.

Indexes ``coalesce(owner_session_id, '')`` for the same reason 0007 does: SQLite
treats NULLs as distinct inside a UNIQUE index, so indexing the raw column would
let two ownerless threshold-triggered jobs run at once and drop the invariant
0001 established.
"""

from alembic import op


revision = "0008_owner_scoped_active_job"
down_revision = "0007_template_ownership"
branch_labels = None
depends_on = None

_ACTIVE = "status IN ('queued', 'running')"


def upgrade() -> None:
    op.drop_index("uq_active_job_per_fingerprint", table_name="generation_jobs")
    op.execute(
        "CREATE UNIQUE INDEX uq_active_job_per_fingerprint "
        "ON generation_jobs (fingerprint_key, coalesce(owner_session_id, '')) "
        f"WHERE {_ACTIVE}"
    )


def downgrade() -> None:
    raise RuntimeError("0008_owner_scoped_active_job is intentionally irreversible")
