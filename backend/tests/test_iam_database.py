from pathlib import Path
from unittest.mock import Mock

import psycopg
import pytest
from sqlalchemy.pool import NullPool

from job_hunter.adapters import aws_config
from job_hunter import migrate_aws


def test_each_connection_signs_a_fresh_token_and_verifies_server(monkeypatch):
    signer = Mock()
    signer.generate_db_auth_token.side_effect = ["token-one", "token-two"]
    monkeypatch.setattr(aws_config.boto3, "client", lambda service: signer)
    connect = Mock()
    monkeypatch.setattr(aws_config.psycopg, "connect", connect)
    engine = aws_config.iam_engine("cluster.example", "jobhunter", "jobhunter_app")
    assert isinstance(engine.pool, NullPool)
    assert engine.url.password is None
    for _ in range(2):
        engine.pool._creator()
    assert [call.kwargs["password"] for call in connect.call_args_list] == ["token-one", "token-two"]
    for call in connect.call_args_list:
        assert call.kwargs["sslmode"] == "verify-full"
        assert call.kwargs["sslrootcert"] == aws_config.RDS_CA
        assert call.kwargs["connect_timeout"] == 5
    assert "BEGIN CERTIFICATE" in Path(aws_config.RDS_CA).read_text()
    signer.generate_db_auth_token.assert_called_with(DBHostname="cluster.example", Port=5432, DBUsername="jobhunter_app")


def test_transient_resume_failure_retries_with_a_new_token(monkeypatch):
    signer = Mock()
    signer.generate_db_auth_token.side_effect = ["first", "second"]
    monkeypatch.setattr(aws_config.boto3, "client", lambda service: signer)
    connect = Mock(side_effect=[psycopg.OperationalError("resuming"), "connected"])
    monkeypatch.setattr(aws_config.psycopg, "connect", connect)
    monkeypatch.setattr(aws_config.time, "sleep", lambda _: None)
    assert aws_config.connect_iam("host", "db", "user") == "connected"
    assert connect.call_count == 2


def test_rejected_authentication_is_not_retried(monkeypatch):
    monkeypatch.setattr(aws_config.boto3, "client", lambda service: Mock())
    connect = Mock(side_effect=psycopg.errors.InvalidPassword("rejected"))
    monkeypatch.setattr(aws_config.psycopg, "connect", connect)
    with pytest.raises(psycopg.errors.InvalidPassword):
        aws_config.connect_iam("host", "db", "user")
    assert connect.call_count == 1


@pytest.mark.parametrize("action", ["migrate", "bootstrap"])
def test_migrations_share_the_iam_or_bootstrap_transaction(monkeypatch, action):
    for key, value in {"DATABASE_HOST": "cluster", "DATABASE_NAME": "jobhunter", "DATABASE_USERNAME": "jobhunter_admin"}.items():
        monkeypatch.setenv(key, value)
    connection = Mock()
    connection.scalar.return_value = None
    engine = Mock()
    engine.begin.return_value.__enter__ = Mock(return_value=connection)
    engine.begin.return_value.__exit__ = Mock(return_value=False)
    iam, bootstrap = Mock(return_value=engine), Mock(return_value=engine)
    monkeypatch.setattr(migrate_aws, "iam_engine", iam)
    monkeypatch.setattr(migrate_aws, "bootstrap_engine", bootstrap)
    upgrade = Mock()
    monkeypatch.setattr(migrate_aws.command, "upgrade", upgrade)
    migrate_aws.handler({"action": action, "credentials": {"username": "jobhunter_admin", "password": "test-only"}}, None)
    assert upgrade.call_args.args[0].attributes["connection"] is connection
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert "SELECT pg_advisory_xact_lock(5224001)" in statements
    assert "REVOKE ALL ON alembic_version FROM jobhunter_app" in statements
    if action == "bootstrap":
        bootstrap.assert_called_once()
        iam.assert_not_called()
        assert "GRANT rds_iam TO jobhunter_app" in statements
        assert "GRANT rds_iam TO jobhunter_admin" in statements
        # Aurora's admin cannot change SUPERUSER/BYPASSRLS, even to restate "NO".
        assert not any("SUPERUSER" in s or "BYPASSRLS" in s for s in statements)
    else:
        iam.assert_called_once()
        bootstrap.assert_not_called()
        assert not any("CREATE ROLE" in statement for statement in statements)
    engine.dispose.assert_called_once()


def test_bootstrap_refuses_a_privileged_runtime_role(monkeypatch):
    for key, value in {"DATABASE_HOST": "cluster", "DATABASE_NAME": "jobhunter", "DATABASE_USERNAME": "jobhunter_admin"}.items():
        monkeypatch.setenv(key, value)
    connection = Mock()
    connection.scalar.side_effect = [1, True]  # Role exists; it is a superuser or bypasses RLS.
    engine = Mock()
    engine.begin.return_value.__enter__ = Mock(return_value=connection)
    engine.begin.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(migrate_aws, "bootstrap_engine", Mock(return_value=engine))
    upgrade = Mock()
    monkeypatch.setattr(migrate_aws.command, "upgrade", upgrade)
    with pytest.raises(RuntimeError, match="row-level security"):
        migrate_aws.handler({"action": "bootstrap", "credentials": {"username": "jobhunter_admin", "password": "test-only"}}, None)
    upgrade.assert_not_called()
    engine.dispose.assert_called_once()
