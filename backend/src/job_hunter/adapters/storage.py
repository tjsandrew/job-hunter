"""Durable object references shared by uploads, imports, exports and cleanup."""
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import boto3
from botocore.exceptions import ClientError
from job_hunter.config import settings

MAX_UPLOAD = 10 * 1024 * 1024


@lru_cache
def s3():
    return boto3.client("s3")


def reference(kind: str, user_id, object_id, extension: str) -> str:
    name = f"{user_id}-{object_id}.{extension}"
    if settings.storage_backend == "s3":
        return f"s3://{settings.document_bucket}/{kind}/{name}"
    directory = Path(settings.pdf_storage_dir).resolve()
    if kind == "uploads":
        directory = directory.parent / "uploads"
    return str(directory / name)


def location(ref: str):
    value = urlsplit(ref)
    if value.scheme != "s3" or value.netloc != settings.document_bucket or not value.path.lstrip("/").startswith(("uploads/", "exports/")):
        raise ValueError("Invalid document reference")
    args = {"Bucket": value.netloc, "Key": value.path.lstrip("/")}
    version = parse_qs(value.query).get("versionId", [None])[0]
    if version:
        args["VersionId"] = version
    return args


def versioned(ref: str, version: str) -> str:
    if not version or version == "null":
        raise RuntimeError("Document bucket versioning must be enabled")
    return ref.split("?", 1)[0] + "?versionId=" + quote(version, safe="")


def write(ref: str, data: bytes, content_type: str) -> str:
    if ref.startswith("s3://"):
        args = location(ref)
        args.pop("VersionId", None)
        result = s3().put_object(**args, Body=data, ContentType=content_type)
        return versioned(ref, result["VersionId"])
    path = Path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def read(ref: str, max_bytes: int = MAX_UPLOAD) -> bytes:
    if not ref.startswith("s3://"):
        return Path(ref).read_bytes()
    try:
        result = s3().get_object(**location(ref))
        body = result["Body"]
        try:
            data = body.read(max_bytes + 1)
        finally:
            body.close()
        if len(data) > max_bytes:
            raise ValueError("Document exceeds size limit")
        return data
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"NoSuchKey", "NoSuchVersion", "404"}:
            raise FileNotFoundError(ref) from exc
        raise


def upload_url(ref: str, content_type: str, size: int) -> str:
    return s3().generate_presigned_url("put_object", Params={**location(ref), "ContentType": content_type, "ContentLength": size}, ExpiresIn=300)


def download_url(ref: str, filename: str, content_type: str) -> str:
    return s3().generate_presigned_url("get_object", Params={**location(ref),
        "ResponseContentDisposition": f'attachment; filename="{filename}"',
        "ResponseContentType": content_type}, ExpiresIn=60)


def capture(ref: str, size: int) -> tuple[str, bytes]:
    args = location(ref)
    try:
        metadata = s3().head_object(**args)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
            raise FileNotFoundError("Uploaded file is not available") from exc
        raise
    if metadata["ContentLength"] != size or size > MAX_UPLOAD:
        raise ValueError("Uploaded byte count does not match the declared size")
    frozen = versioned(ref, metadata.get("VersionId", ""))
    data = read(frozen)
    if len(data) != size:
        raise ValueError("Uploaded byte count does not match the declared size")
    return frozen, data


def delete(ref: str):
    if not ref.startswith("s3://"):
        Path(ref).unlink(missing_ok=True)
        return
    args = location(ref)
    args.pop("VersionId", None)
    # Remove all versions, including presigned-URL overwrites, for this exact key.
    pages = s3().get_paginator("list_object_versions").paginate(Bucket=args["Bucket"], Prefix=args["Key"])
    for page in pages:
        objects = [{"Key": item["Key"], "VersionId": item["VersionId"]}
                   for group in ("Versions", "DeleteMarkers") for item in page.get(group, []) if item["Key"] == args["Key"]]
        if objects:
            result = s3().delete_objects(Bucket=args["Bucket"], Delete={"Objects": objects})
            if result.get("Errors"):
                raise RuntimeError("Document cleanup failed")
