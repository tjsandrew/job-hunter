"""Scope provider listing identifiers to provider boards."""
from alembic import op

revision = "0004_board_scoped_job_ids"
down_revision = "0003_profile_versions"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS uq_job_source_external")
    op.execute("""DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='jobs'::regclass
                     AND conname='uq_job_source_board_external') THEN
        ALTER TABLE jobs ADD CONSTRAINT uq_job_source_board_external UNIQUE(source, source_board, external_id);
      END IF;
    END $$""")

def downgrade():
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS uq_job_source_board_external")
