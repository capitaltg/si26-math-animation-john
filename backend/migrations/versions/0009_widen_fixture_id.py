"""widen template_draft_fixtures.id so derived fixture ids fit on Postgres

Revision ID: 0009_widen_fixture_id
Revises: 0008_owner_scoped_active_job

Every other id in this schema is a bare ``uuid4().hex`` (32 chars), which is why
36 was picked. ``drafts.py`` derives the fixture id instead, as
``f"{draft_id}-fixture-{index}"`` -- 32 hex chars plus a 10-char suffix is 42,
past the declared limit.

SQLite does not enforce VARCHAR lengths, so the bare-metal path stored the long
ids happily and the defect stayed invisible. Postgres does enforce them, so on
the Docker stack every draft persist failed with StringDataRightTruncation, the
generation job went to ``failed``, and the teacher band reported that the
generator had not started.

Postgres-only on purpose: the type widening is a no-op on SQLite, and batch mode
would rebuild a table carrying two foreign keys to do nothing.
"""

import sqlalchemy as sa
from alembic import op


revision = "0009_widen_fixture_id"
down_revision = "0008_owner_scoped_active_job"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.alter_column(
        "template_draft_fixtures",
        "id",
        type_=sa.String(64),
        existing_type=sa.String(36),
        existing_nullable=False,
    )


def downgrade() -> None:
    raise RuntimeError("0009_widen_fixture_id is intentionally irreversible")
