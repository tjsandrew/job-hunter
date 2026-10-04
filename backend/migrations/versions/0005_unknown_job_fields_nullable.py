"""Represent missing location and work mode without inventing values."""
from alembic import op

revision = "0005_unknown_job_fields_nullable"
down_revision = "0004_board_scoped_job_ids"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE jobs ALTER COLUMN location DROP NOT NULL")
    op.execute("ALTER TABLE jobs ALTER COLUMN location DROP DEFAULT")
    op.execute("ALTER TABLE jobs ALTER COLUMN work_mode DROP NOT NULL")
    op.execute("ALTER TABLE jobs ALTER COLUMN work_mode DROP DEFAULT")

def downgrade():
    op.execute("UPDATE jobs SET location='Not stated' WHERE location IS NULL")
    op.execute("UPDATE jobs SET work_mode='Not stated' WHERE work_mode IS NULL")
    op.execute("ALTER TABLE jobs ALTER COLUMN location SET NOT NULL")
    op.execute("ALTER TABLE jobs ALTER COLUMN work_mode SET NOT NULL")
