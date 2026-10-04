"""Store bounded PDF text candidates and deterministic category provenance."""
from alembic import op

revision = "0006_pdf_categories"
down_revision = "0005_unknown_job_fields_nullable"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE uploads ADD COLUMN IF NOT EXISTS sha256 varchar(64)")
    op.execute("ALTER TABLE uploads ADD COLUMN IF NOT EXISTS page_count integer")
    op.execute("ALTER TABLE uploads ADD COLUMN IF NOT EXISTS extracted_text text")
    op.execute("ALTER TABLE uploads ADD COLUMN IF NOT EXISTS error_code varchar(50)")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS category varchar(40)")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS category_source varchar(40)")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS category_evidence varchar(120)")

def downgrade():
    op.drop_column("jobs", "category_evidence")
    op.drop_column("jobs", "category_source")
    op.drop_column("jobs", "category")
    op.drop_column("uploads", "error_code")
    op.drop_column("uploads", "extracted_text")
    op.drop_column("uploads", "page_count")
    op.drop_column("uploads", "sha256")
