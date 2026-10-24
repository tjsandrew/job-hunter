"""Fit analysis: a per-job cache of extracted requirements and each user's latest analysis of a job."""
from alembic import op

revision = '0015_fit_analysis'
down_revision = '0014_ai_tailor_uses'
branch_labels = None
depends_on = None


def upgrade():
    # Shared like jobs: the requirements of a posting are the same for everyone, so they are extracted once.
    op.execute("""CREATE TABLE IF NOT EXISTS job_requirements (
        job_id uuid PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
        input_hash varchar(64) NOT NULL,
        prompt_version varchar(40) NOT NULL,
        model varchar(120) NOT NULL,
        requirements jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now())""")
    # One row per user and job: running the analysis again replaces the row.
    op.execute("""CREATE TABLE IF NOT EXISTS fit_analyses (
        id uuid PRIMARY KEY,
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        status varchar(20) NOT NULL DEFAULT 'pending',
        profile_revision integer,
        result jsonb,
        error_code varchar(60),
        created_at timestamptz NOT NULL DEFAULT now(),
        completed_at timestamptz,
        CONSTRAINT uq_fit_analysis_user_job UNIQUE (user_id, job_id),
        CONSTRAINT ck_fit_analysis_status CHECK (status IN ('pending', 'ready', 'failed')))""")
    op.execute("ALTER TABLE fit_analyses ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE fit_analyses FORCE ROW LEVEL SECURITY")
    op.execute("""DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = current_schema()
                     AND tablename = 'fit_analyses' AND policyname = 'tenant_isolation') THEN
        CREATE POLICY tenant_isolation ON fit_analyses
          USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
          WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);
      END IF;
    END $$""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS fit_analyses")
    op.execute("DROP TABLE IF EXISTS job_requirements")
