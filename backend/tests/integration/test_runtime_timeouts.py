"""Validate the actual bootstrap timeout SQL without persisting role changes."""
import os
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from job_hunter.config import settings
from job_hunter.migrate_aws import grant_runtime

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_INTEGRATION") != "1", reason="requires PostgreSQL")


def test_runtime_limits_are_valid_postgresql_role_defaults():
    capture = Mock()
    grant_runtime(capture)
    statements = [str(call.args[0]) for call in capture.execute.call_args_list
                  if str(call.args[0]).startswith("ALTER ROLE jobhunter_app SET")]
    role = "timeout_check_" + uuid4().hex
    engine = create_engine(settings.migration_database_url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
                for statement in statements:
                    connection.execute(text(statement.replace("jobhunter_app", role)))
                config = connection.execute(text("SELECT rolconfig FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar_one()
                assert set(config) == {"statement_timeout=15s", "idle_in_transaction_session_timeout=30s", "idle_session_timeout=60s"}
            finally:
                transaction.rollback()  # Includes CREATE ROLE and all ALTER ROLE changes.
    finally:
        engine.dispose()
