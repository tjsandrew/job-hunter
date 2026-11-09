"""Password schema releases, explicit one-time operator bootstrap, and plan changes; no HTTP route."""
import logging
import os
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from job_hunter.adapters.aws_config import bootstrap_engine, password_engine
from job_hunter.embedding.db_role import EMBEDDER_ROLE, grant_embedder


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
    # The embed worker's role exists only after the operator bootstrap included its password; until then this
    # is a no-op, and every later release re-applies the (idempotent) grants and policy.
    grant_embedder(connection)


MAX_SET_PLAN_IDS = 20

logger = logging.getLogger(__name__)


def validate_set_plan(event):
    """Exact shape only: a plan from the allow-list and 1-20 UUIDs. Errors never echo the input."""
    if (not isinstance(event, dict) or set(event) != {"action", "plan", "user_ids"} or event["action"] != "set_plan"
            or event["plan"] not in ("free", "premium") or not isinstance(event["user_ids"], list)
            or not 1 <= len(event["user_ids"]) <= MAX_SET_PLAN_IDS
            or not all(isinstance(raw, str) for raw in event["user_ids"])):
        raise ValueError("Invalid set_plan request")
    try:
        ids = [str(uuid.UUID(raw)) for raw in event["user_ids"]]
    except ValueError:
        raise ValueError("Invalid set_plan request") from None
    return event["plan"], list(dict.fromkeys(ids))


def set_plan(connection, plan, user_ids):
    # users has FORCE RLS keyed on app.user_id and the migrator does not bypass it, so
    # UPDATE ... WHERE id = ANY(:ids) would match nothing. Set each tenant's context the
    # way adapters/database.py does; one fixed, parameterised statement per id, one transaction.
    not_found = []
    for user_id in user_ids:
        connection.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": user_id})
        if connection.scalar(text("UPDATE users SET plan = :plan WHERE id = CAST(:user_id AS uuid) RETURNING id"),
                             {"plan": plan, "user_id": user_id}) is None:
            not_found.append(user_id)
    connection.execute(text("SELECT set_config('app.user_id', '', true)"))
    return {"status": "ok", "updated": len(user_ids) - len(not_found), "not_found": not_found}


def handler(event, context):
    host, database = os.environ["DATABASE_HOST"], os.environ["DATABASE_NAME"]
    username = os.environ["DATABASE_USERNAME"]
    if username != "jobhunter_migrator":
        raise ValueError("Unexpected migration role")
    action = event.get("action", "migrate")
    if action not in {"migrate", "check", "bootstrap", "set_plan"}:
        raise ValueError("Unknown migration action")
    if action == "set_plan":
        plan, ids = validate_set_plan(event)
    if action == "bootstrap":
        # Operator retrieves the AWS-managed master secret outside the VPC and
        # invokes over TLS. Never log the event or its credentials.
        credentials = event.get("credentials", {})
        if credentials.get("username") != "jobhunter_admin" or not credentials.get("password"):
            raise ValueError("Bootstrap requires administrator credentials")
        engine = bootstrap_engine(host, database, "jobhunter_admin", credentials["password"])
    else:
        engine = password_engine(host, database, username, attempts=30)   # ~3 minutes: after days paused, Aurora took 81 s to resume
    try:
        if action == "check":
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return {"status": "ready"}
        if action == "set_plan":
            with engine.begin() as connection:
                result = set_plan(connection, plan, ids)
            logging.getLogger().setLevel(logging.INFO)
            logger.info("set_plan plan=%s requested=%d updated=%d not_found=%d",
                        plan, len(ids), result["updated"], len(result["not_found"]))
            return result
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
                # Optional: the embed worker's role (design brief 11). It is created only when its password is
                # supplied, so the two-password bootstrap keeps working unchanged.
                if EMBEDDER_ROLE in passwords:
                    if not isinstance(passwords[EMBEDDER_ROLE], str) or len(passwords[EMBEDDER_ROLE]) < 32:
                        raise ValueError("Bootstrap requires a generated embedder password")
                    if not connection.scalar(text(f"SELECT 1 FROM pg_roles WHERE rolname='{EMBEDDER_ROLE}'")):
                        connection.execute(text(f"CREATE ROLE {EMBEDDER_ROLE} LOGIN"))
                    connection.execute(text(f"REVOKE rds_iam FROM {EMBEDDER_ROLE}"))
                # Utility statements do not accept password bind parameters. psycopg
                # quotes literals, and SQLAlchemy never sees/logs the password SQL.
                from psycopg import sql
                with connection.connection.driver_connection.cursor() as cursor:
                    for role, password in passwords.items():
                        if role not in {"jobhunter_app", "jobhunter_migrator", EMBEDDER_ROLE}:
                            raise ValueError("Unexpected credential role")
                        cursor.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                            sql.Identifier(role), sql.Literal(password)))
                # The RDS/Aurora admin is not a superuser, so it may not even restate
                # NOSUPERUSER/NOBYPASSRLS. New roles default to both; verify instead.
                if connection.scalar(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname='jobhunter_app'")):
                    raise RuntimeError("jobhunter_app must not be a superuser or bypass row-level security")
                if EMBEDDER_ROLE in passwords and connection.scalar(
                        text(f"SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname='{EMBEDDER_ROLE}'")):
                    raise RuntimeError(f"{EMBEDDER_ROLE} must not be a superuser or bypass row-level security")
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            grant_runtime(connection)
        return {"status": "migrated"}
    finally:
        engine.dispose()
