"""Build resumes from the profile bank: pure functions, no database or HTTP.

Two entry points:

* ``suggest_plan`` ranks bank items and points against a job (``keyword-v1``) and
  returns a build plan with the reasons for each pick. It saves nothing.
* ``plan_to_document`` turns a build plan into the parts of a ``documents`` row
  (title, template, content, layout), copying text from the bank and recording
  where each entry and point came from.

A resume is a copy: nothing here writes back to the bank.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from uuid import uuid4

from pydantic import ValidationError

# These helpers hold the skill aliases and tokenising rules used for job ranking.
# They are reused as they are so a skill means the same thing in both places.
from job_hunter.recommendations import (
    _SKILL_ALIASES,
    _canonical_skill,
    _find_skill_evidence,
    _job_skills,
    _normalise_phrase,
    _tokenize,
)

from .dates import (  # noqa: F401  (re-exported for callers of this module)
    DATE_FORMATS,
    DEFAULT_DATE_FORMAT,
    DEFAULT_PRESENT_LABEL,
    PRESENT_LABELS,
    format_date,
    format_date_range,
)
from .settings import LayoutDefaults, ResumeDefaults

STRATEGY_KEYWORD_V1 = "keyword-v1"
DEFAULT_POINTS_PER_ITEM = 4

SECTION_KINDS = ("experience", "education", "projects", "skills", "custom",
                 "certifications", "awards", "volunteering")
LAYOUT_CHOICES = {
    "date_format": DATE_FORMATS,
    "present_label": PRESENT_LABELS,
    "heading_style": ("rule", "small-caps", "bold"),
    "accent_color": ("black", "navy", "teal", "maroon"),
    "bullet_char": ("•", "–", "▪"),
    "header_align": ("center", "left"),
    # "new line" is the spelling the settings API accepted before "newline".
    "contact_separator": ("·", "|", "newline", "new line"),
    "section_spacing": ("compact", "normal", "airy"),
    "skills_layout": ("inline", "grouped", "columns"),
}

DEFAULT_TITLES = {
    "experience": "Experience",
    "education": "Education",
    "projects": "Projects",
    "skills": "Skills",
    "custom": "Additional information",
    "certifications": "Certifications",
    "awards": "Awards",
    "volunteering": "Volunteering",
}
# Plan section kind -> profile item kind it may contain.
_ITEM_KIND_FOR_SECTION = {
    "experience": "experience",
    "education": "education",
    "projects": "project",
    "custom": "custom",
    "certifications": "certification",
    "awards": "award",
    "volunteering": "volunteering",
}
_SECTION_FOR_ITEM_KIND = {value: key for key, value in _ITEM_KIND_FOR_SECTION.items()}
_SKILL_CATEGORY_ORDER = ("language", "framework", "tool", "domain", "soft")
_SKILL_CATEGORY_LABELS = {
    "language": "Languages",
    "framework": "Frameworks",
    "tool": "Tools",
    "domain": "Domain",
    "soft": "Soft skills",
}
_DEFAULT_SECTION_ORDER = ("experience", "education", "projects", "skills", "certifications")
# Resume defaults name the profile kind (singular); a resume section uses the plural.
_DEFAULT_KIND_TO_SECTION = {"certification": "certifications", "award": "awards"}

MAX_SUGGESTED_EXPERIENCE = 4
MAX_SUGGESTED_PROJECTS = 3
MAX_SUGGESTED_EDUCATION = 2
MAX_SUGGESTED_CERTIFICATIONS = 4
MAX_SUGGESTED_SKILLS = 25
MIN_POINTS_PER_ROLE = 2


class BuildError(Exception):
    """A plan that cannot be built; ``status`` is the HTTP status to answer with."""

    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def _not_found() -> BuildError:
    return BuildError(404, "NOT_FOUND", "Resource not found")


# ---------------------------------------------------------------------------
# Resume defaults
# ---------------------------------------------------------------------------

_BUILT_IN_LAYOUT = LayoutDefaults().model_dump(mode="json")


def read_defaults(stored: Mapping | None) -> dict:
    """The keys the user actually saved, or ``{}`` when nothing valid is stored.

    A stored value that no longer validates is ignored rather than breaking
    every new resume.
    """
    try:
        return ResumeDefaults.model_validate(stored or {}).model_dump(mode="json", exclude_unset=True)
    except ValidationError:
        return {}


def effective_defaults(stored: Mapping | None) -> dict:
    """Saved defaults with every missing key filled from the built-in defaults."""
    chosen = read_defaults(stored)
    build = chosen.get("build", {})
    return {
        "template": chosen.get("template", "classic"),
        "layout": {**_BUILT_IN_LAYOUT, **chosen.get("layout", {})},
        "sections": chosen.get("sections", []),
        "header_fields": chosen.get("header_fields") or ["email", "phone", "location", "links"],
        "build": {
            "points_per_item": build.get("points_per_item", DEFAULT_POINTS_PER_ITEM),
            "include_profile_summary": build.get("include_profile_summary", True),
        },
    }


def _section_kind(default_kind: str) -> str:
    """Map a default's kind to a resume section kind; anything unknown is shown as custom."""
    default_kind = _DEFAULT_KIND_TO_SECTION.get(default_kind, default_kind)
    return default_kind if default_kind in SECTION_KINDS else "custom"


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def contact_from_basics(basics: Mapping | None, header_fields=None, include_summary: bool = True) -> dict:
    """Name and the chosen contact fields from profile basics; empty values are left out."""
    basics = basics or {}
    allowed = set(header_fields or ["email", "phone", "location", "links"])
    found = {"name": _text(basics.get("name")) or _text(basics.get("display_name"))}
    for key in ("email", "phone", "location"):
        if key in allowed:
            found[key] = _text(basics.get(key))
    if include_summary:
        found["summary"] = _text(basics.get("summary"))
    return {key: value for key, value in found.items() if value}


# ---------------------------------------------------------------------------
# Blank resumes
# ---------------------------------------------------------------------------

def is_blank_content(content: Mapping) -> bool:
    """A resume with no entries anywhere: nothing the user wrote would be replaced."""
    sections = content.get("sections") or []
    return all(isinstance(section, Mapping) and not section.get("entries") for section in sections)


def blank_document_parts(template: str | None, content: Mapping, layout: Mapping | None,
                         basics: Mapping | None, stored_defaults: Mapping | None) -> tuple[str, dict, dict]:
    """Apply the user's resume defaults and profile basics to a new, empty resume.

    ``template`` and ``layout`` are what the client sent, or ``None`` when it sent nothing.
    A key the client did send wins over the saved default. A user who saved no
    defaults gets exactly the layout they would have got before defaults existed.
    Content that already has entries (a copy, not a new resume) is returned
    unchanged and gets no defaults or profile details.
    """
    base_layout = {"font_size": 11, "margin": 18}
    new_content = deepcopy(dict(content))
    if not is_blank_content(new_content):
        return template or "classic", new_content, {**base_layout, **(layout or {})}

    saved = read_defaults(stored_defaults)
    new_template = template or saved.get("template", "classic")
    new_layout = {**base_layout, **saved.get("layout", {}), **(layout or {})}
    header_fields = saved.get("header_fields")
    include_summary = saved.get("build", {}).get("include_profile_summary", True)
    for key, value in contact_from_basics(basics, header_fields, include_summary).items():
        if not _text(new_content.get(key)):
            new_content[key] = value
    if saved.get("sections"):
        new_content["sections"] = [_default_section(default) for default in saved["sections"]]
    return new_template, new_content, new_layout


def _default_section(default: Mapping) -> dict:
    kind = _section_kind(default["kind"])
    section = {"id": str(uuid4()), "title": default.get("title") or DEFAULT_TITLES[kind],
               "kind": kind, "entries": []}
    if default.get("hidden"):
        section["hidden"] = True
    return section


# ---------------------------------------------------------------------------
# Plan -> document
# ---------------------------------------------------------------------------

def _join(*parts: str, separator: str = " · ") -> str:
    return separator.join(part for part in (_text(part) for part in parts) if part)


def _date_range(data: Mapping) -> dict | None:
    start, end, current = data.get("start"), data.get("end"), bool(data.get("current"))
    if start or end or current:
        return {"start": start, "end": end, "current": current}
    return None


def _entry_labels(kind: str, data: Mapping) -> tuple[str, str]:
    """Heading and subheading text for an item of the given profile kind."""
    if kind == "experience":
        return data.get("title", ""), _join(data.get("organisation", ""), data.get("location", ""))
    if kind == "education":
        return data.get("qualification", ""), _join(data.get("institution", ""), data.get("grade", ""))
    if kind == "project":
        return data.get("name", ""), _join(data.get("role", ""), data.get("url", ""))
    if kind == "certification":
        return data.get("name", ""), data.get("issuer", "")
    if kind == "award":
        return data.get("title", ""), data.get("awarder", "")
    if kind == "volunteering":
        return data.get("title", ""), data.get("organisation", "")
    return data.get("title", ""), data.get("heading", "")


def _find_point(item: Mapping, pick: Mapping) -> tuple[str, str | None, str]:
    """The (bullet_id, alternative_id, text) a pick refers to, from the item's own points."""
    bullet = next((point for point in item["data"].get("bullets", [])
                   if point["id"] == pick["bullet_id"]), None)
    if bullet is None:
        raise _not_found()
    alternative_id = pick.get("alternative_id")
    if alternative_id is None:
        return bullet["id"], None, bullet["text"]
    alternative = next((version for version in bullet.get("alternatives", [])
                        if version["id"] == alternative_id), None)
    if alternative is None:
        raise _not_found()
    return bullet["id"], alternative_id, alternative["text"]


def _entry_from_item(item: Mapping, plan_item: Mapping, layout: Mapping) -> dict:
    data = item["data"]
    heading, subheading = _entry_labels(item["kind"], data)
    date_range = _date_range(data)
    if date_range:
        dates = format_date_range(date_range, layout["date_format"], layout["present_label"])
    else:
        dates = data.get("dates_text") or ""

    bullets: list[str] = []
    bullet_sources: list[dict] = []
    seen: set[str] = set()
    for pick in plan_item.get("picks", []):
        bullet_id, alternative_id, text = _find_point(item, pick)
        if bullet_id in seen:
            raise BuildError(422, "INVALID_PLAN", "A resume uses one wording of each point")
        seen.add(bullet_id)
        bullets.append(text)
        source = {"bullet_id": bullet_id, "base_text": text}
        if alternative_id is not None:
            source["alternative_id"] = alternative_id
        bullet_sources.append(source)

    entry_source = {"item_id": item["id"], "item_revision": item["revision"]}
    if plan_item.get("angle_id") is not None:
        entry_source["angle_id"] = plan_item["angle_id"]
    entry = {"id": str(uuid4()), "heading": heading, "subheading": subheading, "dates": dates,
             "bullets": bullets, "source": entry_source, "bullet_sources": bullet_sources}
    if date_range:
        entry["date_range"] = date_range
    return entry


def _skill_entries(skill_ids: list[str], items: Mapping[str, Mapping]) -> list[dict]:
    """One editable line per category: heading "Languages", point "Python, SQL"."""
    by_category: dict[str, list[str]] = {}
    seen: set[str] = set()
    for skill_id in skill_ids:
        item = items.get(str(skill_id))
        if item is None:
            raise _not_found()
        if item["kind"] != "skill":
            raise BuildError(422, "INVALID_PLAN", "Only skills can go in a skills section")
        if skill_id in seen:
            continue
        seen.add(skill_id)
        category = item["data"].get("category")
        by_category.setdefault(category if category in _SKILL_CATEGORY_LABELS else "domain", []).append(
            item["data"]["name"])
    return [{"id": str(uuid4()), "heading": _SKILL_CATEGORY_LABELS[category], "subheading": "",
             "dates": "", "bullets": [", ".join(by_category[category])]}
            for category in _SKILL_CATEGORY_ORDER if category in by_category]


def _unused_default(defaults_sections: list[Mapping], kind: str, used: set[int]) -> Mapping | None:
    for index, default in enumerate(defaults_sections):
        if index not in used and _section_kind(default["kind"]) == kind:
            used.add(index)
            return default
    return None


def plan_to_document(plan: Mapping, bank: Mapping, basics: Mapping | None, defaults: Mapping | None) -> dict:
    """Turn a build plan into ``{title, template, job_id, content, layout}``.

    ``bank`` is the result of ``get_bank`` (active items only), ``basics`` the
    profile basics and ``defaults`` the user's stored resume defaults (any
    subset of keys, or ``{}``). Raises ``BuildError`` for an unknown, archived or
    foreign item or point, so no partial document is ever returned.
    """
    chosen = effective_defaults(defaults)
    layout = chosen["layout"]
    items = {str(item["id"]): item for item in bank.get("items", [])}

    sections = []
    used_defaults: set[int] = set()
    for plan_section in plan["sections"]:
        kind = plan_section["kind"]
        default = _unused_default(chosen["sections"], kind, used_defaults)
        if kind == "skills":
            entries = _skill_entries([str(value) for value in plan_section.get("skill_ids", [])], items)
        else:
            entries = []
            for plan_item in plan_section.get("items", []):
                item = items.get(str(plan_item["item_id"]))
                if item is None:
                    raise _not_found()
                if item["kind"] != _ITEM_KIND_FOR_SECTION[kind]:
                    raise BuildError(422, "INVALID_PLAN",
                                     f"A {item['kind']} item cannot go in a {kind} section")
                entries.append(_entry_from_item(item, plan_item, layout))
        title = (default or {}).get("title") or DEFAULT_TITLES[kind]
        sections.append({"id": str(uuid4()), "title": title, "kind": kind, "entries": entries})

    summary = plan.get("summary") or {"mode": "profile"}
    if summary["mode"] == "custom":
        summary_text = summary.get("text") or ""
    else:
        summary_text = _text((basics or {}).get("summary"))
    content = {"name": "", "email": "", "phone": "", "location": "", "summary": summary_text, "sections": sections}
    content.update({key: value for key, value in
                    contact_from_basics(basics, chosen["header_fields"], include_summary=False).items()})
    return {"title": plan["title"], "template": plan.get("template") or chosen["template"],
            "job_id": plan.get("job_id"), "content": content, "layout": layout}


# ---------------------------------------------------------------------------
# Suggested plan: keyword-v1
# ---------------------------------------------------------------------------

# Job-title words that say how senior a role is, not what it is about.
_TITLE_NOISE = frozenset({"senior", "junior", "lead", "staff", "principal", "associate", "ii", "iii"})
_SKILL_IN_LIST = 3.0
_SKILL_IN_TEXT = 2.0
_TAG_MATCH = 1.5
_TITLE_WORD = 0.5
_TITLE_WORD_CAP = 1.5
_POINTS_SHARE_OF_ITEM = 0.5


@dataclass
class _Signals:
    """What the job asks for, in the same normal form the ranking uses."""
    terms: dict[str, str]           # canonical skill -> label to show
    listed: set[str]                # canonical skills the job lists explicitly
    title_words: set[str]
    skill_labels: list[str] = field(default_factory=list)


@dataclass
class _Score:
    points: float = 0.0
    skills: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    words: list[str] = field(default_factory=list)

    def reasons(self) -> list[str]:
        found = []
        if self.skills:
            found.append("matches " + ", ".join(self.skills))
        if self.tags:
            found.append("tagged " + ", ".join(self.tags))
        if self.words and not self.skills and not self.tags:
            found.append("mentions " + ", ".join(self.words))
        return found


def _job_signals(job: Mapping, bank_skill_names: list[str]) -> _Signals:
    terms: dict[str, str] = {}
    listed_labels = _job_skills(job)
    for label in listed_labels:
        terms.setdefault(_canonical_skill(label), label)
    # A skill from the bank that the job text names counts even if the job did not list it.
    for hit in _find_skill_evidence(bank_skill_names, job):
        terms.setdefault(_canonical_skill(hit["skill"]), hit["skill"])
    words = set(_tokenize(f"{job.get('title') or ''} {job.get('category') or ''}")) - _TITLE_NOISE
    return _Signals(terms=terms, listed={_canonical_skill(label) for label in listed_labels},
                    title_words=words, skill_labels=listed_labels)


def _mentions(normalised_text: str, canonical: str) -> bool:
    aliases = _SKILL_ALIASES.get(canonical, (canonical,))
    return any(f" {_normalise_phrase(alias)} " in normalised_text for alias in aliases)


def _score_text(text: str, skills, tags, signals: _Signals) -> _Score:
    score = _Score()
    normalised = f" {_normalise_phrase(text)} "
    listed_skills = {_canonical_skill(skill) for skill in skills or [] if isinstance(skill, str)}
    for canonical, label in signals.terms.items():
        if canonical in listed_skills:
            score.points += _SKILL_IN_LIST
            score.skills.append(label)
        elif _mentions(normalised, canonical):
            score.points += _SKILL_IN_TEXT
            score.skills.append(label)
    for tag in tags or []:
        phrase = _normalise_phrase(tag) if isinstance(tag, str) else ""
        if phrase and (phrase in signals.title_words or _canonical_skill(phrase) in signals.terms):
            score.points += _TAG_MATCH
            score.tags.append(tag)
    present = set(normalised.split())
    hits = sorted(signals.title_words & present)
    score.points += min(_TITLE_WORD * len(hits), _TITLE_WORD_CAP)
    score.words = hits
    return score


@dataclass
class _Pick:
    bullet_id: str
    alternative_id: str | None
    score: _Score
    used_alternative: bool = False
    fallback: bool = False

    def reasons(self) -> list[str]:
        if self.fallback:
            return ["no keyword match; kept as a general point"]
        found = self.score.reasons()
        if self.used_alternative:
            found.append("this version fits the job better than the main wording")
        return found


def _best_wording(bullet: Mapping, item_tags, signals: _Signals) -> _Pick:
    """Score the main wording and each version; the main wording wins ties."""
    main_tags = bullet.get("tags") or item_tags
    best = _Pick(bullet["id"], None,
                 _score_text(bullet["text"], bullet.get("skills"), main_tags, signals))
    for version in bullet.get("alternatives", []):
        score = _score_text(version["text"], version.get("skills") or bullet.get("skills"),
                            version.get("tags") or main_tags, signals)
        if score.points > best.score.points:
            best = _Pick(bullet["id"], version["id"], score, used_alternative=True)
    return best


def _pad_date(value: str | None, month: str) -> str:
    if not value:
        return ""
    return value if len(value) == 7 else f"{value}-{month}"


def _recency_key(data: Mapping) -> tuple[str, str]:
    """Sort key where later is newer; a current role is the newest."""
    start = _pad_date(data.get("start"), "01")
    if data.get("current"):
        return ("9999-99", start)
    return (_pad_date(data.get("end"), "12") or start, start)


def _choose_points(item: Mapping, signals: _Signals, limit: int) -> list[_Pick]:
    ranked = [_best_wording(bullet, item.get("tags", []), signals)
              for bullet in item["data"].get("bullets", [])]
    order = {pick.bullet_id: index for index, pick in enumerate(ranked)}
    chosen = sorted((pick for pick in ranked if pick.score.points > 0),
                    key=lambda pick: (-pick.score.points, order[pick.bullet_id]))[:limit]
    wanted = min(MIN_POINTS_PER_ROLE, limit, len(ranked))
    if len(chosen) < wanted:
        taken = {pick.bullet_id for pick in chosen}
        for pick in ranked:
            if len(chosen) >= wanted:
                break
            if pick.bullet_id not in taken:
                pick.fallback = True
                chosen.append(pick)
    return chosen


def _item_text(kind: str, data: Mapping) -> str:
    labels = _entry_labels(kind, data)
    return " ".join([*labels, str(data.get("summary") or "")])


def _plan_item(item: Mapping, picks: list[_Pick]) -> dict:
    plan_picks = []
    for pick in picks:
        entry = {"bullet_id": pick.bullet_id}
        if pick.alternative_id is not None:
            entry["alternative_id"] = pick.alternative_id
        plan_picks.append(entry)
    return {"item_id": item["id"], "picks": plan_picks}


def _bank_skill_canonicals(items: list[Mapping]) -> set[str]:
    """Every skill the bank mentions: skill items plus skills listed on items and points."""
    names: list[str] = []
    for item in items:
        data = item["data"]
        if item["kind"] == "skill":
            names.append(data["name"])
        names.extend(data.get("skills", []))
        for bullet in data.get("bullets", []):
            names.extend(bullet.get("skills", []))
            for version in bullet.get("alternatives", []):
                names.extend(version.get("skills", []))
    return {_canonical_skill(name) for name in names if isinstance(name, str) and name.strip()}


def _coverage(signals: _Signals, items: list[Mapping]) -> dict:
    known = _bank_skill_canonicals(items)
    covered, missing = [], []
    for label in signals.skill_labels:
        (covered if _canonical_skill(label) in known else missing).append(label)
    return {"covered": covered, "missing": missing}


def _section_order(defaults: Mapping | None) -> list[str]:
    order: list[str] = []
    for default in (defaults or {}).get("sections", []):
        kind = _section_kind(default["kind"])
        if kind in _DEFAULT_SECTION_ORDER and kind not in order:
            order.append(kind)
    return order + [kind for kind in _DEFAULT_SECTION_ORDER if kind not in order]


def _plan_title(job: Mapping) -> str:
    title = _text(job.get("title")) or "Resume"
    company = _text(job.get("company"))
    return (f"{title} – {company}" if company else title)[:240]


def suggest_plan(job: Mapping, bank: Mapping, strategy: str = STRATEGY_KEYWORD_V1,
                 points_per_item: int = DEFAULT_POINTS_PER_ITEM, *, template: str = "classic",
                 defaults: Mapping | None = None, include_profile_summary: bool = True) -> dict:
    """Suggest which bank items and points to put on a resume for ``job``.

    ``job`` is a mapping with ``id``, ``title``, ``company``, ``category``,
    ``description`` and ``skills``. ``bank`` is the result of ``get_bank``.
    Returns ``{plan, reasons, coverage, strategy}``. The plan is exactly the body
    ``POST /v1/documents/from-bank`` accepts. Nothing is saved.
    """
    if strategy != STRATEGY_KEYWORD_V1:
        raise BuildError(422, "UNKNOWN_STRATEGY", "Unsupported suggestion strategy")
    items = list(bank.get("items", []))
    skill_items = [item for item in items if item["kind"] == "skill"]
    signals = _job_signals(job, [item["data"]["name"] for item in skill_items])
    reasons: dict[str, list[str]] = {}

    def matching_items(kind: str) -> list[tuple[Mapping, list[_Pick], float, _Score, int]]:
        """Items of the kind that match the job: (item, picks, total score, own score, matching points)."""
        rows = []
        for item in items:
            if item["kind"] != kind:
                continue
            own = _score_text(_item_text(kind, item["data"]), item["data"].get("skills"),
                              [*item.get("tags", []), *item["data"].get("tags", [])], signals)
            picks = _choose_points(item, signals, points_per_item)
            matching = [pick for pick in picks if not pick.fallback and pick.score.points > 0]
            total = own.points + _POINTS_SHARE_OF_ITEM * sum(pick.score.points for pick in matching)
            if total > 0:
                rows.append((item, picks, total, own, len(matching)))
        return rows

    def record(item: Mapping, picks: list[_Pick], own: _Score | None, matching: int, fallback: str | None):
        item_reasons = own.reasons() if own else []
        if matching and not item_reasons:
            item_reasons.append(f"{matching} of its points match this job")
        if fallback:
            item_reasons.append(fallback)
        if item_reasons:
            reasons[item["id"]] = item_reasons
        for pick in picks:
            if pick.reasons():
                reasons[f"{item['id']}:{pick.bullet_id}"] = pick.reasons()

    def suggested_section(kind: str, item_kind: str, cap: int, by_recency: bool,
                          newest_fallback: bool) -> list[dict]:
        matched = matching_items(item_kind)
        chosen = []
        if matched:
            key = (lambda row: _recency_key(row[0]["data"])) if by_recency else (
                lambda row: (row[2], _recency_key(row[0]["data"])))
            for item, picks, _total, own, matching in sorted(matched, key=key, reverse=True)[:cap]:
                record(item, picks, own, matching, None)
                chosen.append(_plan_item(item, picks))
        elif newest_fallback:
            newest = sorted((item for item in items if item["kind"] == item_kind),
                            key=lambda item: _recency_key(item["data"]), reverse=True)[:MIN_POINTS_PER_ROLE]
            for item in newest:
                picks = _choose_points(item, signals, points_per_item)
                record(item, picks, None, 0, "no direct match with the job; most recent of your roles")
                chosen.append(_plan_item(item, picks))
        return chosen

    sections_by_kind: dict[str, dict] = {}
    experience = suggested_section("experience", "experience", MAX_SUGGESTED_EXPERIENCE, True, True)
    if experience:
        sections_by_kind["experience"] = {"kind": "experience", "items": experience}
    projects = suggested_section("projects", "project", MAX_SUGGESTED_PROJECTS, False, False)
    if projects:
        sections_by_kind["projects"] = {"kind": "projects", "items": projects}

    education = sorted((item for item in items if item["kind"] == "education"),
                       key=lambda item: _recency_key(item["data"]), reverse=True)[:MAX_SUGGESTED_EDUCATION]
    if education:
        for item in education:
            reasons[item["id"]] = ["education is included by default"]
        # Education points are kept in their profile order; they are not ranked against the job.
        sections_by_kind["education"] = {"kind": "education", "items": [
            {"item_id": item["id"],
             "picks": [{"bullet_id": bullet["id"]} for bullet in item["data"].get("bullets", [])[:points_per_item]]}
            for item in education]}

    if skill_items:
        def skill_relevance(item: Mapping) -> int:
            canonical = _canonical_skill(item["data"]["name"])
            return 2 if canonical in signals.listed else 1 if canonical in signals.terms else 0
        ordered = sorted(skill_items, key=lambda item: -skill_relevance(item))[:MAX_SUGGESTED_SKILLS]
        for item in ordered:
            relevance = skill_relevance(item)
            if relevance:
                reasons[item["id"]] = ["listed in the job requirements" if relevance == 2
                                       else "mentioned in the job description"]
        sections_by_kind["skills"] = {"kind": "skills", "skill_ids": [item["id"] for item in ordered]}

    certifications = suggested_section("certifications", "certification", MAX_SUGGESTED_CERTIFICATIONS, False, False)
    if certifications:
        sections_by_kind["certifications"] = {"kind": "certifications", "items": certifications}

    plan = {
        "title": _plan_title(job),
        "template": template,
        "job_id": str(job["id"]) if job.get("id") else None,
        "summary": {"mode": "profile"} if include_profile_summary else {"mode": "custom", "text": ""},
        "sections": [sections_by_kind[kind] for kind in _section_order(defaults)
                     if kind in sections_by_kind],
    }
    return {"plan": plan, "reasons": reasons, "coverage": _coverage(signals, items),
            "strategy": STRATEGY_KEYWORD_V1}
