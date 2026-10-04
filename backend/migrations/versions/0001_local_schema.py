"""Initial local schema with PostgreSQL RLS."""
from alembic import op
from job_hunter.domain.models import Base

revision = "0001_local_schema"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=op.get_bind())
    for table, column in {
        "users": "id", "profiles": "user_id", "preferences": "user_id",
        "job_reviews": "user_id", "applications": "user_id", "documents": "user_id",
        "document_exports": "user_id", "uploads": "user_id",
    }.items():
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f'''CREATE POLICY tenant_isolation ON "{table}"
            USING ("{column}" = NULLIF(current_setting('app.user_id', true), '')::uuid)
            WITH CHECK ("{column}" = NULLIF(current_setting('app.user_id', true), '')::uuid)''')

def downgrade():
    for table in ("uploads", "document_exports", "documents", "applications", "job_reviews",
                  "preferences", "profiles", "users"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    Base.metadata.drop_all(bind=op.get_bind())
    op.execute("DROP EXTENSION IF EXISTS vector")
