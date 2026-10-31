"""Shared names and rules of the cloud "pull jobs" path (discovery_worker -> S3 -> import_worker).

The discovery Lambda (outside the VPC, has internet) fetches the public job feeds and stores the normalised records as a
snapshot object ``imports/<pull id>.json``. The import Lambda (inside the VPC, can reach Aurora) loads that object into the
database. Keeping the names here lets both sides and their tests agree on them.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from uuid import UUID

IMPORT_PREFIX = "imports/"
DEFAULT_MAX_NEW = 10         # new jobs one pull may add
MAX_NEW_LIMIT = 200          # upper bound an operator can ask for
MAX_SNAPSHOT_BYTES = 60_000_000   # 21 searches give ~22 MB (about 4 KB a job); room to grow


def import_key(pull_id: str) -> str:
    UUID(pull_id)  # a pull id is always a UUID, so a key cannot climb out of the prefix
    return f"{IMPORT_PREFIX}{pull_id}.json"


def clamp_max_new(value: Any, default: int = DEFAULT_MAX_NEW) -> int:
    """A usable cap from an event or environment value; anything unusable falls back to the default."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(number, MAX_NEW_LIMIT))


def _posted_timestamp(record: Mapping[str, Any]) -> float:
    """When the record was posted, for sorting; a record with no (readable) date sorts after every dated one."""
    value = record.get("posted_at")
    try:
        posted = datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        posted = None
    if posted is None:
        return float("-inf")
    return (posted if posted.tzinfo else posted.replace(tzinfo=timezone.utc)).timestamp()


def interleave(records: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Round-robin the records over the board or search that found them, newest posting first within each.

    A small batch therefore mixes employers, sources and keyword searches instead of being filled by the first
    board in the list, and when a batch cannot take everything it takes the newest postings. Keyword searches share
    one board (all MyCareersFuture results are board "sg"), so the group is ``discovered_by`` when discovery set it,
    and (source, board) for records from older snapshots. Records posted at the same time keep their source order."""
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for record in records:
        found_by = record.get("discovered_by")
        key = ("search", str(found_by)) if found_by else (str(record.get("source") or ""), str(record.get("source_board") or ""))
        groups[key].append(record)
    ordered: list[Mapping[str, Any]] = []
    queues = [deque(sorted(group, key=_posted_timestamp, reverse=True)) for group in groups.values()]
    while queues:
        for queue in queues:
            ordered.append(queue.popleft())
        queues = [queue for queue in queues if queue]
    return ordered
