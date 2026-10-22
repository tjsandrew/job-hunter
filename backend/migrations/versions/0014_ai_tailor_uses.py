"""Record which jobs a user has spent an AI resume tailoring on."""
from alembic import op

revision = '0014_ai_tailor_uses'
down_revision = '0013_job_seniority'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE IF NOT EXISTS ai_tailor_uses (
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (user_id, job_id))""")
    op.execute("ALTER TABLE ai_tailor_uses ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_tailor_uses FORCE ROW LEVEL SECURITY")
    op.execute("""DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = current_schema()
                     AND tablename = 'ai_tailor_uses' AND policyname = 'tenant_isolation') THEN
        CREATE POLICY tenant_isolation ON ai_tailor_uses
          USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
          WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);
      END IF;
    END $$""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS ai_tailor_uses")
