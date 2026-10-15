"""Conservative normalisation of legacy resume dates."""
import calendar
import re

_DATE = re.compile(r"^[0-9]{4}(?:-(?:0[1-9]|1[0-2]))?$")
_MONTHS = {name.casefold(): index for index in range(1, 13) for name in (calendar.month_name[index], calendar.month_abbr[index])}


def is_profile_date(value: str) -> bool:
    return bool(_DATE.fullmatch(value)) and int(value[:4]) > 0


def normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if is_profile_date(value):
        return value
    match = re.fullmatch(r"([A-Za-z]+)\.?\s+([0-9]{4})", value)
    if match and match[1].casefold() in _MONTHS and int(match[2]) > 0:
        return f"{match[2]}-{_MONTHS[match[1].casefold()]:02d}"
    match = re.fullmatch(r"(0?[1-9]|1[0-2])/([0-9]{4})", value)
    if match and int(match[2]) > 0:
        return f"{match[2]}-{int(match[1]):02d}"
    return None


def normalize_dates(value: str | None) -> dict:
    result = {"start": None, "end": None, "current": False}
    if not value or not value.strip():
        return result
    text = value.strip()
    parts = re.split(r"\s*[–—]\s*|\s+[-]\s+|\s+to\s+|(?<=\d{4})-(?=\d{4}|Present|Current|Now)", text, flags=re.IGNORECASE)
    if len(parts) == 1:
        result["start"] = normalize_date(text)
        if result["start"] is None:
            result["dates_text"] = value
        return result
    if len(parts) == 2:
        start, end = parts
        result["start"] = normalize_date(start)
        result["current"] = end.casefold() in {"present", "current", "now"}
        result["end"] = None if result["current"] else normalize_date(end)
        if result["start"] is not None and (result["current"] or result["end"] is not None):
            return result
    result["dates_text"] = value
    return result


normalise_date = normalize_date
normalise_dates = normalize_dates


DATE_FORMATS = ("Jul 2023", "July 2023", "07/2023", "2023")
PRESENT_LABELS = ("Present", "Current", "Now")
DEFAULT_DATE_FORMAT = "Jul 2023"
DEFAULT_PRESENT_LABEL = "Present"


def format_date(value: str | None, date_format: str = DEFAULT_DATE_FORMAT) -> str:
    """Show a `YYYY` or `YYYY-MM` profile date in a resume date format.

    A year-only value has no month to show, so it stays a year in every format.
    The `2023` format always shows just the year.
    """
    if not value or not is_profile_date(value):
        return ""
    year, month = value[:4], int(value[5:7]) if len(value) == 7 else None
    if month is None or date_format == "2023":
        return year
    if date_format == "July 2023":
        return f"{calendar.month_name[month]} {year}"
    if date_format == "07/2023":
        return f"{month:02d}/{year}"
    return f"{calendar.month_abbr[month]} {year}"


def format_date_range(date_range: dict | None, date_format: str = DEFAULT_DATE_FORMAT,
                      present_label: str = DEFAULT_PRESENT_LABEL) -> str:
    """Return display text such as `Jul 2023 – Present`, or an empty string.

    `end: null` with `current: false` means the end is unknown, so only the
    start is shown rather than an open-ended range.
    """
    if not isinstance(date_range, dict):
        return ""
    start = format_date(date_range.get("start"), date_format)
    end = present_label if date_range.get("current") is True else format_date(date_range.get("end"), date_format)
    if start and end:
        return f"{start} – {end}"
    return start or end
