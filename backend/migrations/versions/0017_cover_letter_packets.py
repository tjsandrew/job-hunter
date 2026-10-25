"""Attach an immutable reviewed cover-letter PDF to an application, beside the resume snapshot."""
from alembic import op

revision = "0017_cover_letter_packets"
down_revision = "0016_job_dedup"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS cover_letter_export_id uuid")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS cover_letter_title varchar(240)")
    op.execute("""DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='applications'::regclass
                     AND conname='fk_application_letter_export_owner') THEN
        ALTER TABLE applications ADD CONSTRAINT fk_application_letter_export_owner
          FOREIGN KEY(cover_letter_export_id, user_id) REFERENCES document_exports(id, user_id);
      END IF;
    END $$""")


def downgrade():
    op.execute("ALTER TABLE applications DROP CONSTRAINT IF EXISTS fk_application_letter_export_owner")
    op.execute("ALTER TABLE applications DROP COLUMN IF EXISTS cover_letter_title")
    op.execute("ALTER TABLE applications DROP COLUMN IF EXISTS cover_letter_export_id")
