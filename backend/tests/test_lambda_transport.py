import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from job_hunter.api import main
from job_hunter.api.lambda_handler import handler


def event(path):
    return {"version": "2.0", "routeKey": "$default", "rawPath": path, "rawQueryString": "",
            "headers": {"host": "api.example.test"}, "isBase64Encoded": False,
            "requestContext": {"stage": "$default", "http": {"method": "GET", "path": path,
                               "sourceIp": "127.0.0.1", "protocol": "HTTP/1.1"}}}


def test_gateway_health_event():
    # A public health probe must never open a DB session or wake Aurora.
    def forbidden_db():
        raise AssertionError("Health must not access the database")
    main.app.dependency_overrides[main.db_for] = forbidden_db
    try:
        result = handler(event("/v1/health"), None)
        assert result["statusCode"] == 200
        assert json.loads(result["body"]) == {"status": "ok"}
    finally:
        main.app.dependency_overrides.pop(main.db_for, None)


def test_gateway_preserves_binary_pdf_bytes(monkeypatch):
    data = b"%PDF-1.4\n\xff\x00\x81binary"
    monkeypatch.setattr(main, "owned_document", lambda *_: object())
    monkeypatch.setattr(main, "pdf_bytes", lambda _: data)
    main.app.dependency_overrides[main.db_for] = lambda: None
    try:
        result = handler(event(f"/v1/documents/{uuid4()}/preview.pdf"), None)
        assert result["statusCode"] == 200
        assert result["isBase64Encoded"] is True
        assert base64.b64decode(result["body"]) == data
    finally:
        main.app.dependency_overrides.pop(main.db_for, None)


def test_export_returns_signed_url_json_instead_of_redirect(monkeypatch):
    db = Mock()
    db.info = {"current_user": SimpleNamespace(id=uuid4())}
    db.scalar.return_value = SimpleNamespace(file_path="s3://test/exports/document.pdf?versionId=v1", revision=3)
    monkeypatch.setattr(main.storage, "download_url", lambda *_: "https://documents.example.test/signed")
    main.app.dependency_overrides[main.db_for] = lambda: db
    try:
        result = handler(event(f"/v1/exports/{uuid4()}"), None)
        assert result["statusCode"] == 200
        assert json.loads(result["body"]) == {"url": "https://documents.example.test/signed"}
        assert result["headers"]["cache-control"] == "no-store"
        assert "location" not in result["headers"]
    finally:
        main.app.dependency_overrides.pop(main.db_for, None)
