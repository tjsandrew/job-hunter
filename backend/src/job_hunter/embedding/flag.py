"""The "embed flag": an empty S3 object that wakes the AWS embed worker.

The object carries no information. Its only meaning is "something may need embedding, go and look"; the
worker recomputes what is pending from the database every time (see ``embedding/worker.py`` and
docs/design/11-EMBEDDING-WORKER.md). S3 turns the new object into an SQS message, Lambda's queue
mapping invokes the worker, and nothing in this path needs a NAT gateway or a paid VPC endpoint.

Two rules:

* The flag is written only AFTER the database commit (``request_embedding`` just marks the session, and
  ``get_db`` calls ``send_requested`` once the commit succeeded). Written earlier, the worker could run
  before the rows are visible, find nothing pending and never be woken again.
* Writing it is best effort. A failure is logged and never fails the request that triggered it; the next
  flag (or a manual backfill) picks the rows up because the database is the source of truth.

If the project later has a NAT gateway or an SQS interface endpoint anyway, replace ``write_flag`` with a
direct ``sqs:SendMessage``; the worker does not change.
"""

from __future__ import annotations

import logging
import os
import time
from functools import lru_cache
from uuid import uuid4

FLAG_PREFIX = "embed-requests/"
SESSION_KEY = "embed_flag"
log = logging.getLogger(__name__)


@lru_cache
def _client():
    import boto3
    from botocore.config import Config

    # Short timeouts and a single attempt: this runs after the response is built, and a flag is optional.
    return boto3.client(
        "s3", region_name=os.getenv("AWS_REGION") or "ap-southeast-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"},
                      connect_timeout=2, read_timeout=3, retries={"max_attempts": 1}))


def _bucket() -> str:
    from job_hunter.config import settings
    return settings.document_bucket


def flag_key() -> str:
    """A unique, human-readable key. Nothing reads it; uniqueness only keeps every write a new object."""
    return f"{FLAG_PREFIX}{time.time_ns()}-{uuid4().hex[:8]}"


def request_embedding(session) -> None:
    """Mark that this request changed something the embed worker should pick up (written after commit)."""
    session.info[SESSION_KEY] = True


def write_flag(*, client=None, bucket: str | None = None) -> bool:
    """Write one flag object. Returns whether it was written; never raises."""
    try:
        target = bucket if bucket is not None else _bucket()
        if not target:
            log.warning("embed flag not written: no document bucket configured")
            return False
        (client or _client()).put_object(Bucket=target, Key=flag_key(), Body=b"")
        return True
    except Exception:
        log.exception("embed flag not written; the next flag or a manual backfill will pick the rows up")
        return False


def send_requested(session, *, client=None, bucket: str | None = None) -> bool:
    """Call after the commit: writes the flag if the request marked the session. Never raises."""
    if not session.info.pop(SESSION_KEY, False):
        return False
    return write_flag(client=client, bucket=bucket)
