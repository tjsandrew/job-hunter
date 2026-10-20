from io import BytesIO
import time
from uuid import uuid4

import boto3
from botocore.stub import Stubber
from fastapi import HTTPException
import pytest
from starlette.requests import Request

from job_hunter.adapters.auth import cloud_identity
from job_hunter.adapters import storage
from job_hunter.config import settings


def claims_request(claims=None):
    scope = {"type": "http", "headers": [(b"x-dev-user", b"alice"), (b"authorization", b"Bearer forged")]}
    if claims is not None:
        scope["aws.event"] = {"requestContext": {"authorizer": {"jwt": {"claims": claims}}}}
    return Request(scope)


@pytest.fixture
def valid_claims(monkeypatch):
    monkeypatch.setattr(settings, "cognito_issuer", "https://cognito-idp.ap-southeast-1.amazonaws.com/pool")
    monkeypatch.setattr(settings, "cognito_client_id", "test-client")
    return {"iss": settings.cognito_issuer, "client_id": "test-client", "token_use": "access",
            "exp": str(time.time() + 3600), "scope": "openid jobhunter/use", "sub": str(uuid4())}


def test_cloud_identity_ignores_forged_client_headers():
    with pytest.raises(HTTPException) as error:
        cloud_identity(claims_request())
    assert error.value.status_code == 401


@pytest.mark.parametrize("field,value", [("iss", "https://attacker.test"), ("client_id", "other"),
                         ("token_use", "id"), ("exp", "1"), ("scope", "openid"), ("sub", "alice")])
def test_cloud_identity_rejects_wrong_token_context(valid_claims, field, value):
    valid_claims[field] = value
    with pytest.raises(HTTPException):
        cloud_identity(claims_request(valid_claims))


def test_cloud_tenant_is_stable_and_distinct(valid_claims):
    first = cloud_identity(claims_request(valid_claims))
    assert cloud_identity(claims_request(valid_claims)).user_id == first.user_id
    valid_claims["sub"] = str(uuid4())
    assert cloud_identity(claims_request(valid_claims)).user_id != first.user_id


@pytest.fixture
def s3_stub(monkeypatch):
    monkeypatch.setattr(settings, "document_bucket", "test-documents")
    client = boto3.client("s3", region_name="ap-southeast-1", aws_access_key_id="testing", aws_secret_access_key="testing")
    monkeypatch.setattr(storage, "s3", lambda: client)
    with Stubber(client) as stub:
        yield stub
        stub.assert_no_pending_responses()


def test_capture_reads_the_head_version_even_if_latest_changes(s3_stub):
    args = {"Bucket": "test-documents", "Key": "uploads/user-upload.pdf"}
    s3_stub.add_response("head_object", {"ContentLength": 3, "VersionId": "frozen-version"}, args)
    s3_stub.add_response("get_object", {"Body": BytesIO(b"PDF")}, {**args, "VersionId": "frozen-version"})
    ref, data = storage.capture("s3://test-documents/uploads/user-upload.pdf", 3)
    assert data == b"PDF" and ref.endswith("?versionId=frozen-version")


def test_capture_rejects_declared_size_mismatch_before_read(s3_stub):
    s3_stub.add_response("head_object", {"ContentLength": 4, "VersionId": "v1"},
                         {"Bucket": "test-documents", "Key": "uploads/test.pdf"})
    with pytest.raises(ValueError):
        storage.capture("s3://test-documents/uploads/test.pdf", 3)


def test_capture_requires_versioned_storage(s3_stub):
    s3_stub.add_response("head_object", {"ContentLength": 3},
                         {"Bucket": "test-documents", "Key": "uploads/test.pdf"})
    with pytest.raises(RuntimeError):
        storage.capture("s3://test-documents/uploads/test.pdf", 3)


def test_storage_rejects_other_buckets_and_unowned_prefixes(monkeypatch):
    monkeypatch.setattr(settings, "document_bucket", "test-documents")
    for ref in ("s3://other/uploads/test.pdf", "s3://test-documents/secrets/test"):
        with pytest.raises(ValueError):
            storage.location(ref)


def test_s3_missing_key_becomes_missing_document(s3_stub):
    s3_stub.add_client_error("get_object", "NoSuchKey", expected_params={"Bucket": "test-documents", "Key": "uploads/test.pdf"})
    with pytest.raises(FileNotFoundError):
        storage.read("s3://test-documents/uploads/test.pdf")
