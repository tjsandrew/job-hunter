"""Pinned JSON Resume validation with no runtime schema downloads."""
import json
from pathlib import Path
from urllib.parse import urlsplit
import re

from jsonschema import Draft7Validator, FormatChecker
from pydantic import BaseModel, ConfigDict, Field
from .text import ImportFailure

SCHEMA = json.loads(Path(__file__).with_name('json_resume_v1_schema.json').read_text())
CHECKER = FormatChecker()


@CHECKER.checks('uri', raises=ValueError)
def valid_uri(value):
    return not isinstance(value, str) or bool(urlsplit(value).scheme) and not any(char.isspace() for char in value)


class JsonResume(BaseModel):
    model_config = ConfigDict(extra='allow')
    basics: dict = Field(default_factory=dict)
    work: list[dict] = Field(default_factory=list)
    education: list[dict] = Field(default_factory=list)
    projects: list[dict] = Field(default_factory=list)
    skills: list[dict] = Field(default_factory=list)
    certificates: list[dict] = Field(default_factory=list)
    awards: list[dict] = Field(default_factory=list)
    volunteer: list[dict] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


MAX_DEPTH = 64


def within_depth(value, limit=MAX_DEPTH):
    """Iterative nesting check, so hostile input can't hit Python's recursion limit later (deepcopy, dumps)."""
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > limit:
            return False
        children = current.values() if isinstance(current, dict) else current if isinstance(current, list) else ()
        stack.extend((child, depth + 1) for child in children)
    return True


def validate_resume(value):
    if not isinstance(value, dict):
        raise ImportFailure('INVALID_JSON_RESUME', 'JSON Resume must be an object')
    if not within_depth(value):
        raise ImportFailure('INVALID_JSON_RESUME', 'Resume JSON is nested too deeply')
    try:
        JsonResume.model_validate(value)
    except ValueError as exc:
        raise ImportFailure('INVALID_JSON_RESUME', 'Resume sections must be objects and lists') from exc
    try:
        too_large = len(json.dumps(value, ensure_ascii=False).encode()) > 1024 * 1024
    except RecursionError as exc:
        raise ImportFailure('INVALID_JSON_RESUME', 'Resume JSON is nested too deeply') from exc
    if too_large:
        raise ImportFailure('INPUT_TOO_LARGE', 'Resume JSON must be at most 1 MiB')
    errors = sorted(Draft7Validator(SCHEMA, format_checker=CHECKER).iter_errors(value), key=lambda error: str(list(error.path)))
    if errors:
        first = errors[0]
        raise ImportFailure('INVALID_JSON_RESUME', f"Invalid JSON Resume field: {'.'.join(map(str, first.path)) or 'root'}")
    return value
