"""Add seniority columns to jobs, filled at ingestion like category.

Seniority levels (intern, junior, mid, senior, lead, executive) are a property of the job, so they live on the job row and
are set by the shared classifier (job_hunter/seniority.py) at ingestion, next to jobs.category. ``seniority`` is
a JSON list ([] = names no level, NULL = not classified yet); ``seniority_source`` says which classifier (or
"stated") produced it; ``seniority_evidence`` is the matched phrase. Values in the legacy match-features table
are copied before that table is retired; other existing rows stay NULL until import or ``--reclassify``.
"""
from alembic import op

revision = '0013_job_seniority'
down_revision = '0012_embedding_tables'
branch_labels = None
depends_on = None


def upgrade():
    # IF NOT EXISTS: a fresh database builds jobs from the ORM model in 0001, which already has these columns.
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS seniority json")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS seniority_source varchar(40)")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS seniority_evidence varchar(120)")
    op.execute("""DO $$ BEGIN
      IF to_regclass('job_match_features') IS NOT NULL THEN
        UPDATE jobs AS job SET
          -- the earlier five-level ladder called junior "entry"
          seniority = replace((feature.features->'seniority_levels')::text, '"entry"', '"junior"')::json,
          seniority_source = CASE WHEN feature.features->>'seniority_source' = 'stated'
                                  THEN 'stated' ELSE 'legacy-features-v2' END
        FROM job_match_features AS feature
        WHERE feature.job_id = job.id
          AND jsonb_typeof(feature.features->'seniority_levels') = 'array'
          AND job.seniority IS NULL;
        DROP TABLE job_match_features;
      END IF;
    END $$""")


def downgrade():
    op.execute("""CREATE TABLE IF NOT EXISTS job_match_features (
        job_id uuid PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
        feature_version varchar(40) NOT NULL,
        features jsonb NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""INSERT INTO job_match_features (job_id, feature_version, features)
        SELECT id, 'features-v2', jsonb_build_object('seniority_levels',
            -- back to the earlier five-level ladder: junior was "entry" and executive did not exist
            replace(replace(seniority::text, '"junior"', '"entry"'), '"executive"', '"lead"')::jsonb,
            'seniority_source', seniority_source, 'role_family', category)
        FROM jobs WHERE seniority IS NOT NULL
        ON CONFLICT (job_id) DO NOTHING""")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS seniority_evidence")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS seniority_source")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS seniority")
