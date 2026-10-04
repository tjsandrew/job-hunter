"""Attach immutable reviewed resume exports and saved cover-letter text to applications."""
from alembic import op

revision = "0009_application_packets"
down_revision = "0008_upload_declared_size"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='document_exports'::regclass
                     AND conname='uq_document_export_id_user') THEN
        ALTER TABLE document_exports ADD CONSTRAINT uq_document_export_id_user UNIQUE(id, user_id);
      END IF;
    END $$""")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS resume_export_id uuid")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS resume_title varchar(240)")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS cover_letter_text text")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS packet_updated_at timestamptz")
    op.execute("""DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='applications'::regclass
                     AND conname='fk_application_resume_export_owner') THEN
        ALTER TABLE applications ADD CONSTRAINT fk_application_resume_export_owner
          FOREIGN KEY(resume_export_id, user_id) REFERENCES document_exports(id, user_id);
      END IF;
    END $$""")

def downgrade():
    op.execute("ALTER TABLE applications DROP CONSTRAINT IF EXISTS fk_application_resume_export_owner")
    op.execute("ALTER TABLE applications DROP COLUMN IF EXISTS packet_updated_at")
    op.execute("ALTER TABLE applications DROP COLUMN IF EXISTS cover_letter_text")
    op.execute("ALTER TABLE applications DROP COLUMN IF EXISTS resume_title")
    op.execute("ALTER TABLE applications DROP COLUMN IF EXISTS resume_export_id")
    op.execute("ALTER TABLE document_exports DROP CONSTRAINT IF EXISTS uq_document_export_id_user")
