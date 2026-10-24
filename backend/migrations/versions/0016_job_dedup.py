"""Cross-source de-duplication: link rows that are the same posting.

Each source keeps its own row in ``jobs`` (so a re-import stays idempotent and no review, application, fit analysis, tailored
document or vector is orphaned). ``match_key`` is normalised employer + title + location; ``canonical_job_id`` is NULL on the row
users see and points at the canonical row on its duplicates; ``also_seen_on`` lists, on the canonical row, the other sources of
the same posting. All three stay NULL until the next import of a job or ``python -m job_hunter.import_jobs --relink``; a job with
no link is shown exactly as before.
"""
from alembic import op

revision = '0016_job_dedup'
down_revision = '0015_fit_analysis'
branch_labels = None
depends_on = None


def upgrade():
    # IF NOT EXISTS: a fresh database builds jobs from the ORM model in 0001, which already has these columns and indexes.
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS canonical_job_id uuid REFERENCES jobs(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS match_key varchar(500)")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS also_seen_on json")
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_canonical_job_id ON jobs (canonical_job_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_match_key ON jobs (match_key)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_jobs_match_key")
    op.execute("DROP INDEX IF EXISTS ix_jobs_canonical_job_id")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS also_seen_on")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS match_key")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS canonical_job_id")
