"""Add provider metadata and scope external IDs by provider."""
from alembic import op

revision = "0002_job_source_fields"
down_revision = "0001_local_schema"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_board varchar(255)")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_url text")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS fetched_at timestamptz")
    # Earlier bootstraps may have made external_id globally unique. Provider IDs only
    # need to be unique within a source, so remove that single-column constraint.
    op.execute("""DO $$ DECLARE c record; BEGIN
      FOR c IN SELECT conname FROM pg_constraint
        WHERE conrelid='jobs'::regclass AND contype='u'
        AND (SELECT array_agg(a.attname ORDER BY a.attname)
             FROM unnest(conkey) k(attnum)
             JOIN pg_attribute a ON a.attrelid=conrelid AND a.attnum=k.attnum) = ARRAY['external_id']::name[]
      LOOP EXECUTE format('ALTER TABLE jobs DROP CONSTRAINT %I', c.conname); END LOOP;
    END $$""")
    op.execute("""DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='jobs'::regclass
                     AND conname='uq_job_source_external') THEN
        ALTER TABLE jobs ADD CONSTRAINT uq_job_source_external UNIQUE(source, external_id);
      END IF;
    END $$""")

def downgrade():
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS uq_job_source_external")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS source_board")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS source_url")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS fetched_at")
