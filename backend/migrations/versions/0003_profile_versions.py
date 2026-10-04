"""Persist immutable user-confirmed profile revisions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_profile_versions"
down_revision = "0002_job_source_fields"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""CREATE TABLE IF NOT EXISTS profile_versions (
        id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id), revision integer NOT NULL,
        data json NOT NULL, content_hash varchar(64) NOT NULL, created_at timestamptz NOT NULL,
        CONSTRAINT uq_profile_version_user_revision UNIQUE(user_id, revision))""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_profile_versions_user_id ON profile_versions(user_id)")
    op.execute("ALTER TABLE profile_versions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE profile_versions FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY tenant_isolation ON profile_versions
       USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
       WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)""")

def downgrade():
    op.drop_table("profile_versions")
