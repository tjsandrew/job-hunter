"""Verified TLS connections: short-lived for the workers, one reused connection per API Lambda instance."""
import os
from pathlib import Path
import time

import boto3
import psycopg
from sqlalchemy import URL, create_engine
from sqlalchemy.pool import NullPool, QueuePool

# Postgres closes a pooled API connection after this long idle, so warm but idle Lambda instances never keep Aurora from
# auto-pausing; the pool's pre-ping then reconnects on the next request.
IDLE_SESSION_TIMEOUT = "60s"

RDS_CA = str(Path(__file__).with_name("rds-ca-bundle.crt"))


def connect_iam(host: str, database: str, username: str, *, attempts: int = 4):
    # Sign locally per physical connection, including reconnects in warm Lambdas.
    client = boto3.client("rds")
    for attempt in range(attempts):
        token = client.generate_db_auth_token(DBHostname=host, Port=5432, DBUsername=username)
        try:
            return psycopg.connect(host=host, port=5432, dbname=database, user=username,
                                   password=token, sslmode="verify-full", sslrootcert=RDS_CA,
                                   connect_timeout=5)
        except psycopg.OperationalError as exc:
            # Retry transient connection establishment failures, never a SQL
            # transaction and never a rejected authentication decision.
            if exc.sqlstate not in {None, "57P03", "08001", "08006"} or attempt == attempts - 1:
                raise
            time.sleep(1)


def iam_engine(host: str, database: str, username: str, *, attempts: int = 4):
    url = URL.create("postgresql+psycopg", host=host, port=5432, database=database, username=username)
    # Close physical connections instead of keeping Aurora awake in idle pools.
    return create_engine(url, creator=lambda: connect_iam(host, database, username, attempts=attempts),
                         poolclass=NullPool, hide_parameters=True)


def bootstrap_engine(host: str, database: str, username: str, password: str):
    # Initial operator setup only. Password never enters an env variable or URL.
    url = URL.create("postgresql+psycopg", host=host, database=database, username=username)
    return create_engine(url, creator=lambda: psycopg.connect(
        host=host, port=5432, dbname=database, user=username, password=password,
        sslmode="verify-full", sslrootcert=RDS_CA, connect_timeout=30),
        poolclass=NullPool, hide_parameters=True)


def password_engine(host: str, database: str, username: str, *, attempts: int = 4,
                    password: str | None = None, reuse: bool = False):
    """``reuse=False`` (workers): a new physical connection each time. ``reuse=True`` (the API): one connection per Lambda
    instance, kept between requests. Opening a verified-TLS, SCRAM-authenticated connection for every request kept a 1-ACU
    Aurora busy under load. Reuse is safe for tenant isolation: ``app.user_id`` is set with ``set_config(..., true)``,
    which Postgres clears at the end of every transaction."""
    credential = password if password is not None else os.environ.get("DATABASE_PASSWORD", "")
    if not credential:
        raise ValueError("DATABASE_PASSWORD is required for cloud password authentication")
    def connect():
        for attempt in range(attempts):
            try:
                return psycopg.connect(host=host, port=5432, dbname=database, user=username,
                                       password=credential, sslmode="verify-full", sslrootcert=RDS_CA,
                                       connect_timeout=5,
                                       **({"options": f"-c idle_session_timeout={IDLE_SESSION_TIMEOUT}"} if reuse else {}))
            except psycopg.OperationalError as exc:
                # Authentication errors can have no sqlstate during connection startup.
                message = str(exc).lower()
                if (exc.sqlstate not in {None, "57P03", "08001", "08006"}
                        or "authentication failed" in message or attempt == attempts - 1):
                    raise
                time.sleep(1)
    url = URL.create("postgresql+psycopg", host=host, database=database, username=username)
    if reuse:   # a Lambda instance serves one request at a time; the overflow covers a rare second session in a request
        return create_engine(url, creator=connect, poolclass=QueuePool, pool_size=1, max_overflow=2, pool_timeout=10,
                             pool_pre_ping=True, pool_recycle=300, hide_parameters=True)
    return create_engine(url, creator=connect, poolclass=NullPool, hide_parameters=True)
