"""Persist the result returned by idempotent import apply."""
from alembic import op

revision = '0011_profile_import_result'
down_revision = '0010_profile_bank'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE profile_imports ADD COLUMN IF NOT EXISTS applied_result jsonb')
    op.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS basics_provenance jsonb NOT NULL DEFAULT '{}'")


def downgrade():
    op.execute('ALTER TABLE profile_imports DROP COLUMN IF EXISTS applied_result')
    op.execute('ALTER TABLE profiles DROP COLUMN IF EXISTS basics_provenance')
