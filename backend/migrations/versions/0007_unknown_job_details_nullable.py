"""Keep omitted listing employer and description values unknown."""
from alembic import op

revision = "0007_job_nullables"
down_revision = "0006_pdf_categories"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE jobs ALTER COLUMN company DROP NOT NULL")
    op.execute("ALTER TABLE jobs ALTER COLUMN description DROP NOT NULL")
    op.execute("ALTER TABLE jobs ALTER COLUMN description DROP DEFAULT")

def downgrade():
    op.execute("UPDATE jobs SET company='Not stated' WHERE company IS NULL")
    op.execute("UPDATE jobs SET description='' WHERE description IS NULL")
    op.execute("ALTER TABLE jobs ALTER COLUMN company SET NOT NULL")
    op.execute("ALTER TABLE jobs ALTER COLUMN description SET NOT NULL")
