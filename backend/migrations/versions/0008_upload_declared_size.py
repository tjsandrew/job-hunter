"""Record and enforce the size announced at upload initiation."""
from alembic import op

revision = "0008_upload_declared_size"
down_revision = "0007_job_nullables"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE uploads ADD COLUMN IF NOT EXISTS declared_size integer")
    op.execute("UPDATE uploads SET declared_size=0 WHERE declared_size IS NULL")
    op.alter_column("uploads", "declared_size", nullable=False)

def downgrade():
    op.drop_column("uploads", "declared_size")
