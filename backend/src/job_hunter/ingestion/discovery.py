"""Read-only, bounded discovery from documented public employer ATS feeds."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import logging
import os
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards"
LEVER_API = "https://api.lever.co/v0/postings"
SMARTRECRUITERS_API = "https://api.smartrecruiters.com/v1/companies"
USER_AGENT = "JobHunter-PoC/1.0 (public employer job-board reader)"


@dataclass(frozen=True)
class DiscoveryConfig:
    """Source board tokens and strict request/result bounds for one preview/run."""

    greenhouse_boards: Sequence[str] = ()
    lever_boards: Sequence[str] = ()
    smartrecruiters_boards: Sequence[str] = ()
    timeout_seconds: float = 10.0
    page_size: int = 100
    max_pages_per_board: int = 10
    max_records_per_board: int = 1000
    singapore_only: bool = False

    def __post_init__(self) -> None:
        if not 0 < self.timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be between 0 and 60")
        if not 1 <= self.page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if not 1 <= self.max_pages_per_board <= 10:
            raise ValueError("max_pages_per_board must be between 1 and 10")
        if not 1 <= self.max_records_per_board <= 1000:
            raise ValueError("max_records_per_board must be between 1 and 1000")


@dataclass
class DiscoveryReport:
    jobs: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    truncated_boards: list[str] = field(default_factory=list)


class ProviderHTTPError(RuntimeError):
    """An HTTP response failure with a stable provider-neutral classification."""

    def __init__(self, provider: str, status: int, url: str) -> None:
        self.provider = provider
        self.status = status
        self.url = url
        self.kind = "rate_limited" if status == 429 else (
            "server_error" if status >= 500 else "http_error"
        )
        super().__init__(f"{provider} returned HTTP {status} ({self.kind})")


class ProviderRequestError(RuntimeError):
    """Transport, timeout, or malformed-response failure."""

    def __init__(self, provider: str, kind: str, detail: str) -> None:
        self.provider = provider
        self.kind = kind
        super().__init__(f"{provider} request failed ({kind}): {detail}")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def _break(self) -> None:
        if self.parts and self.parts[-1] != "\n":
            self.parts.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag == "br":
            self._break()
        elif tag == "li":
            self._break()
            self.parts.append("• ")
        elif tag in {"p", "div", "ul", "ol", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._break()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"p", "div", "li", "ul", "ol", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._break()

    def handle_data(self, data: str) -> None:
        # Keep author-provided plain-text line breaks while collapsing noisy
        # indentation and repeated spaces within each line.
        lines = [" ".join(line.split()) for line in data.splitlines()]
        text = "\n".join(line for line in lines if line)
        if text:
            self.parts.append(text)


def _clean_description(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    text = str(value)
    # Greenhouse content can contain HTML entities that encode HTML markup.
    import html

    for _ in range(3):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    parser = _TextExtractor()
    try:
        parser.feed(text)
        parser.close()
        result = "".join(parser.parts)
    except Exception:
        result = " ".join(text.split())
    normalized_lines = [" ".join(line.split()) for line in result.splitlines()]
    normalized_lines = [line for line in normalized_lines if line]
    readable_lines: list[str] = []
    for index, line in enumerate(normalized_lines):
        # Lever plain-text descriptions sometimes serialize a bullet marker
        # and its item as separate lines. Rejoin those without flattening the
        # boundaries between actual list items or paragraphs.
        if line in {"•", "▪", "◦", "*", "-"} and index + 1 < len(normalized_lines):
            readable_lines.append(line + " " + normalized_lines[index + 1])
            continue
        if index and normalized_lines[index - 1] in {"•", "▪", "◦", "*", "-"}:
            continue
        readable_lines.append(line)
    result = "\n".join(readable_lines)
    return result or None


def _lever_description(raw: Mapping[str, Any]) -> str | None:
    """Combine Lever's documented description, extra lists, and closing text.

    Lever's ``lists`` carries separately-labelled requirement/benefit sections;
    these do not appear in ``descriptionPlain``. Preserve their headings and
    list item boundaries so the saved description remains readable and useful.
    """
    opening = _clean_description(raw.get("descriptionPlain") or raw.get("description"))
    sections: list[str] = [opening] if opening else []
    lists = raw.get("lists")
    if isinstance(lists, list):
        for item in lists:
            if not isinstance(item, Mapping):
                continue
            heading = _clean_description(item.get("text"))
            content = _clean_description(item.get("contentPlain") or item.get("content"))
            if heading and content:
                sections.append(f"{heading}\n{content}")
            elif heading:
                sections.append(heading)
            elif content:
                sections.append(content)
    additional = _clean_description(raw.get("additionalPlain") or raw.get("additional"))
    if additional:
        sections.append(additional)
    return "\n\n".join(sections) or None


def _iso_datetime(value: Any, *, milliseconds: bool = False) -> str | None:
    if value is None or value == "":
        return None
    try:
        if milliseconds and isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fetch_json(url: str, timeout: float, provider: str) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(8_000_000)
            if response.read(1):
                raise ProviderRequestError(provider, "response_too_large", "response exceeded 8 MB")
    except HTTPError as exc:
        raise ProviderHTTPError(provider, exc.code, url) from exc
    except (TimeoutError, URLError, OSError) as exc:
        kind = "timeout" if isinstance(exc, TimeoutError) or "timed out" in str(exc).lower() else "network_error"
        raise ProviderRequestError(provider, kind, str(exc)) from exc
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderRequestError(provider, "invalid_json", str(exc)) from exc


def _salary(value: Any, currency: Any = None, period: Any = None) -> tuple[Any, Any, str | None, str | None]:
    if not isinstance(value, Mapping):
        return None, None, None, None
    low, high = value.get("min"), value.get("max")
    currency = value.get("currency", currency)
    period = value.get("interval", period)
    return low, high, str(currency) if currency else None, str(period) if period else None


def _normalise(
    *, source: str, board: str, raw: Mapping[str, Any], fetched_at: str
) -> dict[str, Any] | None:
    if source == "greenhouse":
        external_id = raw.get("id")
        location_obj = raw.get("location") or {}
        location = location_obj.get("name") if isinstance(location_obj, Mapping) else None
        title = raw.get("title")
        employer = raw.get("company_name") or board
        url = raw.get("absolute_url")
        description = raw.get("content")
        work_mode = None
        posted_at = _iso_datetime(raw.get("first_published"))
        expires_at = _iso_datetime(raw.get("application_deadline"))
        salary_min = salary_max = salary_currency = salary_period = None
    elif source == "lever":
        external_id = raw.get("id")
        categories = raw.get("categories") or {}
        location = categories.get("location") if isinstance(categories, Mapping) else None
        if isinstance(categories, Mapping) and categories.get("allLocations"):
            locs = categories["allLocations"]
            if isinstance(locs, list):
                location = ", ".join(str(item) for item in locs if item) or location
        title = raw.get("text")
        employer = raw.get("company") or board
        url = raw.get("hostedUrl") or raw.get("applyUrl")
        description = _lever_description(raw)
        work_mode = raw.get("workplaceType")
        posted_at = _iso_datetime(raw.get("createdAt"), milliseconds=True)
        expires_at = None
        salary_min, salary_max, salary_currency, salary_period = _salary(raw.get("salaryRange"))
    else:
        external_id = raw.get("id")
        company = raw.get("company") or {}
        employer = company.get("name") if isinstance(company, Mapping) else None
        location_obj = raw.get("location") or {}
        if isinstance(location_obj, Mapping):
            location_parts = [
                location_obj.get(key)
                for key in ("city", "region", "country")
                if location_obj.get(key)
            ]
            location = ", ".join(dict.fromkeys(str(part).strip() for part in location_parts)) or None
            work_mode = "remote" if location_obj.get("remote") is True else None
        else:
            location, work_mode = None, None
        title = raw.get("name")
        url = raw.get("applyUrl") or raw.get("jobAdUrl")
        description = raw.get("jobAd", {}).get("jobDescription") if isinstance(raw.get("jobAd"), Mapping) else None
        posted_at = _iso_datetime(raw.get("releasedDate"))
        expires_at = None
        salary_min, salary_max, salary_currency, salary_period = _salary(raw.get("compensation"))

    if external_id is None or not title or not url:
        return None
    external_id = str(external_id)
    return {
        "source": source,
        "source_board": board,
        "external_id": external_id,
        "source_url": str(url),
        "title": str(title).strip(),
        "employer": str(employer).strip() if employer else None,
        "location": str(location).strip() if location else None,
        "work_mode": str(work_mode).strip() if work_mode else None,
        "description": description if source == "lever" else _clean_description(description),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "salary_period": salary_period,
        "posted_at": posted_at,
        "expires_at": expires_at,
        "fetched_at": fetched_at,
        "dedup_key": f"{source}:{board}:{external_id}",
    }


def _is_singapore(job: Mapping[str, Any]) -> bool:
    return "singapore" in (job.get("location") or "").casefold()


def _discover_greenhouse(board: str, config: DiscoveryConfig) -> tuple[list[dict[str, Any]], bool]:
    # The documented Greenhouse jobs endpoint returns the full public board and
    # documents no page parameter. Read one bounded response; never invent a cursor.
    url = f"{GREENHOUSE_API}/{quote(board, safe='')}/jobs?{urlencode({'content': 'true'})}"
    payload = _fetch_json(url, config.timeout_seconds, "greenhouse")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("jobs"), list):
        raise ProviderRequestError("greenhouse", "invalid_schema", "expected an object with jobs[]")
    fetched_at = _now_utc()
    raw_jobs = payload["jobs"]
    result = [
        normalized
        for raw in raw_jobs[: config.max_records_per_board]
        if isinstance(raw, Mapping)
        if (normalized := _normalise(source="greenhouse", board=board, raw=raw, fetched_at=fetched_at))
    ]
    if config.singapore_only:
        result = [job for job in result if _is_singapore(job)]
    return result, len(raw_jobs) > config.max_records_per_board


def _discover_lever(board: str, config: DiscoveryConfig) -> tuple[list[dict[str, Any]], bool]:
    result: list[dict[str, Any]] = []
    truncated = False
    page_limit = min(config.page_size, config.max_records_per_board)
    for page in range(config.max_pages_per_board):
        skip = page * page_limit
        remaining = config.max_records_per_board - len(result)
        if remaining <= 0:
            truncated = True
            break
        limit = min(page_limit, remaining)
        query = urlencode({"mode": "json", "skip": skip, "limit": limit})
        url = f"{LEVER_API}/{quote(board, safe='')}?{query}"
        payload = _fetch_json(url, config.timeout_seconds, "lever")
        if not isinstance(payload, list):
            raise ProviderRequestError("lever", "invalid_schema", "expected a JSON array")
        fetched_at = _now_utc()
        page_jobs = [
            normalized
            for raw in payload
            if isinstance(raw, Mapping)
            if (normalized := _normalise(source="lever", board=board, raw=raw, fetched_at=fetched_at))
        ]
        result.extend(page_jobs)
        if len(payload) < limit:
            break
        if page == config.max_pages_per_board - 1:
            truncated = True
    if config.singapore_only:
        result = [job for job in result if _is_singapore(job)]
    return result, truncated


def _discover_smartrecruiters(board: str, config: DiscoveryConfig) -> tuple[list[dict[str, Any]], bool]:
    """Read the documented public Posting API, constrained to Singapore country."""
    result: list[dict[str, Any]] = []
    truncated = False
    page_limit = min(config.page_size, config.max_records_per_board)
    total_found: int | None = None
    for page in range(config.max_pages_per_board):
        offset = page * page_limit
        remaining = config.max_records_per_board - len(result)
        if remaining <= 0:
            truncated = True
            break
        limit = min(page_limit, remaining)
        query = urlencode({"limit": limit, "offset": offset, "country": "sg"})
        url = f"{SMARTRECRUITERS_API}/{quote(board, safe='')}/postings?{query}"
        payload = _fetch_json(url, config.timeout_seconds, "smartrecruiters")
        if not isinstance(payload, Mapping) or not isinstance(payload.get("content"), list):
            raise ProviderRequestError("smartrecruiters", "invalid_schema", "expected object with content[]")
        try:
            total_found = int(payload.get("totalFound"))
        except (TypeError, ValueError):
            total_found = None
        fetched_at = _now_utc()
        raw_jobs = payload["content"]
        page_jobs = [
            normalized
            for raw in raw_jobs
            if isinstance(raw, Mapping)
            if (normalized := _normalise(source="smartrecruiters", board=board, raw=raw, fetched_at=fetched_at))
            # Enforce an explicit Singapore location locally as well as using
            # the documented country filter; never include a worldwide-only role.
            if "singapore" in str((normalized or {}).get("location") or "").casefold()
        ]
        result.extend(page_jobs)
        if len(raw_jobs) < limit or (total_found is not None and offset + len(raw_jobs) >= total_found):
            break
        if page == config.max_pages_per_board - 1:
            truncated = True
    if total_found is not None and total_found > config.max_records_per_board and len(result) >= config.max_records_per_board:
        truncated = True
    return result, truncated


def discover_report(config: DiscoveryConfig) -> DiscoveryReport:
    """Fetch configured boards; isolate a failed board from successful boards."""
    report = DiscoveryReport()
    sources: list[tuple[str, Sequence[str], Callable[[str, DiscoveryConfig], tuple[list[dict[str, Any]], bool]]]] = [
        ("greenhouse", config.greenhouse_boards, _discover_greenhouse),
        ("lever", config.lever_boards, _discover_lever),
        ("smartrecruiters", config.smartrecruiters_boards, _discover_smartrecruiters),
    ]
    for source, boards, fetch in sources:
        for board in boards:
            try:
                jobs, truncated = fetch(board, config)
                report.jobs.extend(jobs)
                if truncated:
                    report.truncated_boards.append(f"{source}:{board}")
            except (ProviderHTTPError, ProviderRequestError) as exc:
                item = {"source": source, "board": board, "kind": exc.kind, "error": str(exc)}
                report.failures.append(item)
                logger.warning("Job board discovery failed: %s", item)
    return report


def discover(config: DiscoveryConfig | Mapping[str, Any]) -> list[dict[str, Any]]:
    """Convenience interface returning only normalized records.

    `config` may be a DiscoveryConfig or a mapping with its field names.
    Failures are logged and do not prevent successful boards from returning.
    Use :func:`discover_report` when callers need failure/truncation details.
    """
    if isinstance(config, Mapping):
        config = DiscoveryConfig(**config)
    if not isinstance(config, DiscoveryConfig):
        raise TypeError("config must be DiscoveryConfig or a mapping")
    return discover_report(config).jobs


def _config_from_env(args: argparse.Namespace) -> DiscoveryConfig:
    greenhouse = args.greenhouse or [v.strip() for v in os.getenv("GREENHOUSE_BOARDS", "").split(",") if v.strip()]
    lever = args.lever or [v.strip() for v in os.getenv("LEVER_BOARDS", "").split(",") if v.strip()]
    smartrecruiters = args.smartrecruiters or [v.strip() for v in os.getenv("SMARTRECRUITERS_BOARDS", "").split(",") if v.strip()]
    return DiscoveryConfig(
        greenhouse_boards=greenhouse,
        lever_boards=lever,
        smartrecruiters_boards=smartrecruiters,
        timeout_seconds=args.timeout,
        page_size=args.page_size,
        max_pages_per_board=args.max_pages,
        max_records_per_board=args.max_records,
        singapore_only=args.singapore_only,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preview current public Greenhouse/Lever job listings")
    parser.add_argument("--greenhouse", action="append", default=[], help="Greenhouse public board token (repeatable)")
    parser.add_argument("--lever", action="append", default=[], help="Lever public site token (repeatable)")
    parser.add_argument("--smartrecruiters", action="append", default=[], help="SmartRecruiters public company identifier (repeatable)")
    parser.add_argument("--singapore-only", action="store_true")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--max-records", type=int, default=1000)
    parser.add_argument("--limit", type=int, default=10, help="maximum records printed")
    args = parser.parse_args(argv)
    config = _config_from_env(args)
    if not config.greenhouse_boards and not config.lever_boards and not config.smartrecruiters_boards:
        parser.error("configure a public board with --greenhouse, --lever, or --smartrecruiters")
    report = discover_report(config)
    print(json.dumps({
        "fetched_at": _now_utc(),
        "count": len(report.jobs),
        "failures": report.failures,
        "truncated_boards": report.truncated_boards,
        "preview": report.jobs[: max(0, args.limit)],
    }, ensure_ascii=False, indent=2))
    return 1 if report.failures and not report.jobs else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
