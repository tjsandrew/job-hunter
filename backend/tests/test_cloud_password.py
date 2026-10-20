from unittest.mock import Mock, patch

import psycopg
import pytest
from sqlalchemy.pool import NullPool

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
