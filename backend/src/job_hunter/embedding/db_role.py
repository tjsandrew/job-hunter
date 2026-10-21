"""Database role of the AWS embed worker: ``jobhunter_embedder`` (see docs/design/11-EMBEDDING-WORKER.md, section 5).

Least privilege, not a superuser and not ``BYPASSRLS`` (the managed Aurora admin cannot grant that attribute):

* SELECT on the tables the worker reads: ``jobs``, ``profiles``, ``profile_versions``, ``preferences``;
* SELECT, INSERT and UPDATE on the tables it writes: ``job_embeddings``, ``profile_embeddings``;
* ONE extra row-level-security policy, read-only and on ``profiles`` only, so it can list the users who
  have a confirmed profile. Everything else about a user stays behind the normal per-user policy: the
  worker sets ``app.user_id`` for each user before reading or writing that user's rows.

The role itself is created outside this module (the operator bootstrap in the cloud, ``infra/local/init-db.sql``
locally), because creating a role needs privileges the migration role does not have. ``grant_embedder`` is
idempotent and does nothing when the role does not exist yet, so it is safe to run on every release.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine, text

EMBEDDER_ROLE = "jobhunter_embedder"
READ_TABLES = ("jobs", "profiles", "profile_versions", "preferences")
WRITE_TABLES = ("job_embeddings", "profile_embeddings")
POLICY_NAME = "embedder_list_users"


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def role_exists(connection) -> bool:
    return connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": EMBEDDER_ROLE}) == 1


def grant_embedder(connection) -> bool:
    """Apply the embed worker's grants and policy. Returns False (and changes nothing) if the role is missing."""
    if not role_exists(connection):
        return False
    role = _ident(EMBEDDER_ROLE)
    database = _ident(connection.scalar(text("SELECT current_database()")))
    # The worker keeps a transaction open while the model runs, so its idle limits are longer than the app role's.
    for statement in (
        f"ALTER ROLE {role} SET statement_timeout = '120s'",
        f"ALTER ROLE {role} SET idle_in_transaction_session_timeout = '10min'",
        f"ALTER ROLE {role} SET idle_session_timeout = '20min'",
        f"GRANT CONNECT ON DATABASE {database} TO {role}",
        f"GRANT USAGE ON SCHEMA public TO {role}",
        f"GRANT SELECT ON {', '.join(READ_TABLES)} TO {role}",
        f"GRANT SELECT, INSERT, UPDATE ON {', '.join(WRITE_TABLES)} TO {role}",
        f"DROP POLICY IF EXISTS {POLICY_NAME} ON profiles",
        f"CREATE POLICY {POLICY_NAME} ON profiles FOR SELECT TO {role} USING (true)",
    ):
        connection.execute(text(statement))
    return True


def main() -> int:  # pragma: no cover - local convenience, run by the Compose API start-up command
    url = os.getenv("MIGRATION_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("MIGRATION_DATABASE_URL is required")
    engine = create_engine(url)
    with engine.begin() as connection:
        applied = grant_embedder(connection)
    print(f"embedder role grants {'applied' if applied else 'skipped (role does not exist)'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
