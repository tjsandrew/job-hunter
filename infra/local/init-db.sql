-- Local development credentials only. PostgreSQL exposes no public host port.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE ROLE jobhunter_app LOGIN PASSWORD 'jobhunter_app' NOSUPERUSER NOBYPASSRLS;
GRANT CONNECT ON DATABASE jobhunter TO jobhunter_app;
GRANT USAGE ON SCHEMA public TO jobhunter_app;
ALTER DEFAULT PRIVILEGES FOR ROLE jobhunter IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO jobhunter_app;
ALTER DEFAULT PRIVILEGES FOR ROLE jobhunter IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO jobhunter_app;
-- Role of the AWS embed worker, so it can be exercised locally. Its grants and the one extra row-level-security
-- policy are applied by `python -m job_hunter.embedding.db_role` (the Compose API start-up runs it).
CREATE ROLE jobhunter_embedder LOGIN PASSWORD 'jobhunter_embedder' NOSUPERUSER NOBYPASSRLS;
