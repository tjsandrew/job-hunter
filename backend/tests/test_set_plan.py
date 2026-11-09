"""Operator ``set_plan`` validation and Lambda handler, without a database.

The code under test lives in ``job_hunter.migrate_aws``. Importing it pulls in alembic
and ``job_hunter.adapters.aws_config`` (boto3/psycopg), which is fine inside the API
container.
"""
import logging
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest

from job_hunter import migrate_aws
from job_hunter.migrate_aws import MAX_SET_PLAN_IDS, validate_set_plan


def event(plan="free", user_ids=None):
    return {"action": "set_plan", "plan": plan, "user_ids": user_ids if user_ids is not None else [str(uuid4())]}


def test_valid_event_returns_plan_and_canonical_lowercase_deduped_ids():
    upper = "123E4567-E89B-12D3-A456-426614174000"
    lower = "123e4567-e89b-12d3-a456-426614174000"
    other = str(uuid4())
    plan, ids = validate_set_plan(event("premium", [upper, lower, other]))
    assert plan == "premium"
    assert ids == [lower, other]  # uppercase -> lowercase, duplicate collapsed


@pytest.mark.parametrize("plan", ["free", "premium"])
def test_accepts_both_plans(plan):
    user_id = str(uuid4())
    assert validate_set_plan(event(plan, [user_id])) == (plan, [user_id])


def test_ids_keep_first_seen_order():
    a, b, c = (str(uuid4()) for _ in range(3))
    plan, ids = validate_set_plan(event("free", [b, a, c, b]))
    assert plan == "free"
    assert ids == [b, a, c]


def test_accepts_exactly_twenty_ids():
    ids = [str(uuid4()) for _ in range(MAX_SET_PLAN_IDS)]
    assert validate_set_plan(event("free", ids))[1] == ids


@pytest.mark.parametrize("plan", ["Premium", "pro", "", None, " premium"])
def test_rejects_bad_plan(plan):
    with pytest.raises(ValueError):
        validate_set_plan(event(plan))


def test_rejects_more_than_twenty_ids():
    with pytest.raises(ValueError):
        validate_set_plan(event("free", [str(uuid4()) for _ in range(MAX_SET_PLAN_IDS + 1)]))


def test_rejects_empty_list():
    with pytest.raises(ValueError):
        validate_set_plan(event("free", []))


@pytest.mark.parametrize("user_ids", [str(uuid4()), (str(uuid4()),)])
def test_rejects_non_list(user_ids):
    with pytest.raises(ValueError):
        validate_set_plan(event("free", user_ids))


def test_rejects_extra_key():
    with pytest.raises(ValueError):
        validate_set_plan({**event(), "sql": "SELECT 1"})


@pytest.mark.parametrize("missing", [
    {"action": "set_plan", "user_ids": [str(uuid4())]},   # no plan
    {"action": "set_plan", "plan": "free"},               # no user_ids
    {"plan": "free", "user_ids": [str(uuid4())]},         # no action
])
def test_rejects_missing_key(missing):
    with pytest.raises(ValueError):
        validate_set_plan(missing)


def test_rejects_wrong_action():
    with pytest.raises(ValueError):
        validate_set_plan({"action": "migrate", "plan": "free", "user_ids": [str(uuid4())]})


@pytest.mark.parametrize("bad", ["abc", 123, "1; DROP TABLE users"])
def test_rejects_non_uuid_item(bad):
    with pytest.raises(ValueError):
        validate_set_plan(event("free", [str(uuid4()), bad]))


def test_handler_validates_before_creating_engine(monkeypatch):
    for key, value in {"DATABASE_HOST": "cluster.example", "DATABASE_NAME": "jobhunter",
                       "DATABASE_USERNAME": "jobhunter_migrator"}.items():
        monkeypatch.setenv(key, value)
    password = Mock()
    monkeypatch.setattr(migrate_aws, "password_engine", password)
    with pytest.raises(ValueError):
        migrate_aws.handler({"action": "set_plan", "plan": "pro", "user_ids": [str(uuid4())]}, None)
    password.assert_not_called()


def test_handler_returns_result_and_never_logs_user_ids(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    for key, value in {"DATABASE_HOST": "cluster.example", "DATABASE_NAME": "jobhunter",
                       "DATABASE_USERNAME": "jobhunter_migrator"}.items():
        monkeypatch.setenv(key, value)
    user_id = str(uuid4())
    connection = MagicMock()
    engine = Mock()
    engine.begin.return_value.__enter__ = Mock(return_value=connection)
    engine.begin.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(migrate_aws, "password_engine", Mock(return_value=engine))
    monkeypatch.setattr(migrate_aws, "set_plan",
                        Mock(return_value={"status": "ok", "updated": 1, "not_found": []}))
    result = migrate_aws.handler({"action": "set_plan", "plan": "premium", "user_ids": [user_id]}, None)
    assert result == {"status": "ok", "updated": 1, "not_found": []}
    assert user_id not in caplog.text
    engine.dispose.assert_called_once()


def test_no_api_code_can_reach_set_plan():
    # Plan changes are operator-only: nothing behind API Gateway imports the migrate handler or writes users.plan,
    # so no client input can reach this path. The API role also has no lambda:InvokeFunction (infra/aws/backend/permissions.tf).
    from pathlib import Path
    import job_hunter.api
    for source in Path(job_hunter.api.__file__).parent.rglob("*.py"):
        code = source.read_text()
        assert "migrate_aws" not in code and "set_plan" not in code, source
        assert "SET plan" not in code and ".plan =" not in code, source
