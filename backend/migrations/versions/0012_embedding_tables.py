"""Add separate tables for job/profile embeddings and job match features.

New tables only: no existing table or column is changed, so the resume edit/intake flow is untouched.
The older ``embedding`` columns on ``jobs`` and ``profile_versions`` are left as they are (unused).
"""
from alembic import op

revision = '0012_embedding_tables'
down_revision = '0011_profile_import_result'
branch_labels = None
depends_on = None


def upgrade():
    # One row per job per embedding text format (e.g. job-v1). Re-embedding replaces the row for that
    # format; a new format adds a row, so formats can be compared side by side. Jobs are shared data
    # (no row-level security), like the jobs table itself.
    op.execute("""CREATE TABLE IF NOT EXISTS job_embeddings (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        text_version varchar(40) NOT NULL,
        model text,
        dimensions integer,
        input_hash varchar(64),
        status varchar(20) NOT NULL,
        reason text,
        embedding vector(512),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_job_embedding_version UNIQUE (job_id, text_version),
        CONSTRAINT ck_job_embedding_status CHECK (status IN ('ready', 'pending', 'failed', 'no_content')),
        CONSTRAINT ck_job_embedding_vector CHECK ((status = 'ready') = (embedding IS NOT NULL)))""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_job_embeddings_status ON job_embeddings(status)")

    # Same shape for profile versions, owned by a user and protected by the same per-user row-level
    # security policy as profile_versions.
    op.execute("""CREATE TABLE IF NOT EXISTS profile_embeddings (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL REFERENCES users(id),
        profile_version_id uuid NOT NULL REFERENCES profile_versions(id) ON DELETE CASCADE,
        text_version varchar(40) NOT NULL,
        model text,
        dimensions integer,
        input_hash varchar(64),
        status varchar(20) NOT NULL,
        reason text,
        embedding vector(512),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_profile_embedding_version UNIQUE (profile_version_id, text_version),
        CONSTRAINT ck_profile_embedding_status CHECK (status IN ('ready', 'pending', 'failed', 'no_content')),
        CONSTRAINT ck_profile_embedding_vector CHECK ((status = 'ready') = (embedding IS NOT NULL)))""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_profile_embeddings_user_id ON profile_embeddings(user_id)")
    op.execute("ALTER TABLE profile_embeddings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE profile_embeddings FORCE ROW LEVEL SECURITY")
    op.execute("""DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = current_schema()
                     AND tablename = 'profile_embeddings' AND policyname = 'tenant_isolation') THEN
        CREATE POLICY tenant_isolation ON profile_embeddings
          USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
          WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);
      END IF;
    END $$""")

    # Properties of a job that sit outside the vector (seniority levels and where they came from).
    # Role family is not stored: jobs.category already holds it.
    op.execute("""CREATE TABLE IF NOT EXISTS job_match_features (
        job_id uuid PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
        feature_version varchar(40) NOT NULL,
        features jsonb NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now())""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS profile_embeddings")
    op.execute("DROP TABLE IF EXISTS job_match_features")
    op.execute("DROP TABLE IF EXISTS job_embeddings")
