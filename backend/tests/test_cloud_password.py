from unittest.mock import Mock, patch

import psycopg
import pytest
from sqlalchemy.pool import NullPool, QueuePool

from job_hunter.adapters.aws_config import password_engine, RDS_CA


def test_password_connection_uses_verified_tls_and_no_idle_pool(monkeypatch):
    monkeypatch.setenv("DATABASE_PASSWORD", "not-a-real-password")
    with patch("job_hunter.adapters.aws_config.psycopg.connect", return_value=Mock()) as connect:
        engine = password_engine("db.example", "jobhunter", "jobhunter_app")
        assert isinstance(engine.pool, NullPool)
        engine.pool._creator()
        assert connect.call_args.kwargs["sslmode"] == "verify-full"
        assert connect.call_args.kwargs["sslrootcert"] == RDS_CA
        assert "not-a-real-password" not in str(engine.url)


def test_password_is_required(monkeypatch):
    monkeypatch.delenv("DATABASE_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="DATABASE_PASSWORD"):
        password_engine("db.example", "jobhunter", "jobhunter_app")


def test_rejected_password_is_never_retried():
    with patch("job_hunter.adapters.aws_config.psycopg.connect",
               side_effect=psycopg.OperationalError("password authentication failed")) as connect:
        engine = password_engine("db.example", "jobhunter", "jobhunter_app", password="test", attempts=12)
        with pytest.raises(psycopg.OperationalError):
            engine.pool._creator()
        assert connect.call_count == 1


def test_the_api_reuses_one_connection_that_postgres_closes_when_idle(monkeypatch):
    monkeypatch.setenv("DATABASE_PASSWORD", "not-a-real-password")
    with patch("job_hunter.adapters.aws_config.psycopg.connect", return_value=Mock()) as connect:
        engine = password_engine("db.example", "jobhunter", "jobhunter_app", reuse=True)
        assert isinstance(engine.pool, QueuePool) and engine.pool.size() == 1 and engine.pool._pre_ping
        engine.pool._creator()
        assert connect.call_args.kwargs["sslmode"] == "verify-full"
        assert connect.call_args.kwargs["options"] == "-c idle_session_timeout=60s"   # idle Lambdas never block auto-pause
    with patch("job_hunter.adapters.aws_config.psycopg.connect", return_value=Mock()) as connect:
        password_engine("db.example", "jobhunter", "jobhunter_app").pool._creator()
        assert "options" not in connect.call_args.kwargs                               # workers: unchanged
