"""set_plan against real PostgreSQL with row-level security enforced.

Local migrations run as a superuser, which ignores RLS; the AWS migrator does not. So these tests
connect as jobhunter_app (NOBYPASSRLS, like jobhunter_migrator) to exercise the same RLS path.
"""
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, text

from job_hunter.config import settings
from job_hunter.domain.models import User
from job_hunter.migrate_aws import set_plan

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_INTEGRATION") != "1",
                                reason="set RUN_DB_INTEGRATION=1 against local PostgreSQL")


def context(connection, user_id):
    connection.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})


def read_plan(engine, user_id):
    with engine.connect() as connection:
        context(connection, user_id)
        return connection.execute(text("SELECT plan FROM users WHERE id = :uid"), {"uid": user_id}).scalar_one()


def rls_engine():
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        assert not connection.scalar(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"))
    return engine


def test_set_plan_updates_existing_users_and_reports_missing():
    engine = rls_engine()
    a, b, c = uuid4(), uuid4(), uuid4()
    missing = uuid4()
    try:
        with engine.begin() as connection:
            for user_id in (a, b, c):
                context(connection, user_id)
                connection.execute(insert(User).values(id=user_id, auth_subject=f"set-plan-{user_id}",
                                                       display_name="Set plan test", plan="free"))

        with engine.begin() as connection:
            # Why set_plan sets app.user_id per row: under RLS a plain ANY(:ids) update sees no rows.
            naive = connection.execute(text("UPDATE users SET plan = 'premium' WHERE id = ANY(:ids)"), {"ids": [a, b]})
            assert naive.rowcount == 0
        with engine.begin() as connection:
            result = set_plan(connection, "premium", [str(a), str(b), str(missing)])
        assert result == {"status": "ok", "updated": 2, "not_found": [str(missing)]}

        assert read_plan(engine, a) == "premium"
        assert read_plan(engine, b) == "premium"
        assert read_plan(engine, c) == "free"

        with engine.begin() as connection:
            switched = set_plan(connection, "free", [str(a)])
        assert switched == {"status": "ok", "updated": 1, "not_found": []}
        assert read_plan(engine, a) == "free"
    finally:
        with engine.begin() as connection:
            for user_id in (a, b, c):
                context(connection, user_id)
                connection.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
        engine.dispose()
