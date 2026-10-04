-- Local development credentials only. PostgreSQL exposes no public host port.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE ROLE jobhunter_app LOGIN PASSWORD 'jobhunter_app' NOSUPERUSER NOBYPASSRLS;
GRANT CONNECT ON DATABASE jobhunter TO jobhunter_app;
GRANT USAGE ON SCHEMA public TO jobhunter_app;
ALTER DEFAULT PRIVILEGES FOR ROLE jobhunter IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO jobhunter_app;
ALTER DEFAULT PRIVILEGES FOR ROLE jobhunter IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO jobhunter_app;
