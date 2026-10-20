"""Password schema releases and explicit one-time operator bootstrap; no HTTP route."""
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from job_hunter.adapters.aws_config import bootstrap_engine, password_engine


def grant_runtime(connection):
    # Server-side cleanup also covers a Lambda killed before its finally block.
    # Keep migration/admin sessions independent of these request-time limits.
    connection.execute(text("ALTER ROLE jobhunter_app SET statement_timeout = '15s'"))
    connection.execute(text("ALTER ROLE jobhunter_app SET idle_in_transaction_session_timeout = '30s'"))
    connection.execute(text("ALTER ROLE jobhunter_app SET idle_session_timeout = '60s'"))
    connection.execute(text("GRANT CONNECT ON DATABASE jobhunter TO jobhunter_app"))
    connection.execute(text("GRANT USAGE ON SCHEMA public TO jobhunter_app"))
    connection.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO jobhunter_app"))
    connection.execute(text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO jobhunter_app"))
    connection.execute(text("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO jobhunter_app"))
    connection.execute(text("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO jobhunter_app"))
    connection.execute(text("REVOKE ALL ON alembic_version FROM jobhunter_app"))


def handler(event, context):
    host, database = os.environ["DATABASE_HOST"], os.environ["DATABASE_NAME"]
    username = os.environ["DATABASE_USERNAME"]
    if username != "jobhunter_migrator":
        raise ValueError("Unexpected migration role")
    action = event.get("action", "migrate")
    if action not in {"migrate", "check", "bootstrap"}:
        raise ValueError("Unknown migration action")
    if action == "bootstrap":
        # Operator retrieves the AWS-managed master secret outside the VPC and
        # invokes over TLS. Never log the event or its credentials.
        credentials = event.get("credentials", {})
        if credentials.get("username") != "jobhunter_admin" or not credentials.get("password"):
            raise ValueError("Bootstrap requires administrator credentials")
        engine = bootstrap_engine(host, database, "jobhunter_admin", credentials["password"])
    else:
        engine = password_engine(host, database, username, attempts=12)
    try:
        if action == "check":
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return {"status": "ready"}
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(5224001)"))
            if action == "bootstrap":
                if not connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname='jobhunter_app'")):
                    connection.execute(text("CREATE ROLE jobhunter_app LOGIN PASSWORD NULL"))
                passwords = event.get("passwords", {})
                if not all(isinstance(passwords.get(role), str) and len(passwords[role]) >= 32
                           for role in ("jobhunter_app", "jobhunter_migrator")):
                    raise ValueError("Bootstrap requires generated application and migration passwords")
                if not connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname='jobhunter_migrator'")):
                    connection.execute(text("CREATE ROLE jobhunter_migrator LOGIN"))
                connection.execute(text("REVOKE rds_iam FROM jobhunter_app, jobhunter_admin, jobhunter_migrator"))
                connection.execute(text("GRANT jobhunter_admin TO jobhunter_migrator"))
                # Utility statements do not accept password bind parameters. psycopg
                # quotes literals, and SQLAlchemy never sees/logs the password SQL.
                from psycopg import sql
                with connection.connection.driver_connection.cursor() as cursor:
                    for role, password in passwords.items():
                        if role not in {"jobhunter_app", "jobhunter_migrator"}:
                            raise ValueError("Unexpected credential role")
                        cursor.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                            sql.Identifier(role), sql.Literal(password)))
                # The RDS/Aurora admin is not a superuser, so it may not even restate
                # NOSUPERUSER/NOBYPASSRLS. New roles default to both; verify instead.
                if connection.scalar(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname='jobhunter_app'")):
                    raise RuntimeError("jobhunter_app must not be a superuser or bypass row-level security")
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            grant_runtime(connection)
        return {"status": "migrated"}
    finally:
        engine.dispose()
