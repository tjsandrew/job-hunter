"""Pure JSON Resume v1 export; app-specific facts remain lossless in metadata."""
from copy import deepcopy
from datetime import date, datetime
from uuid import UUID
from urllib.parse import urlsplit
import re


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(child) for child in value]
    return deepcopy(value)


def _dates(data):
    return {key: data[field] for key, field in (("startDate", "start"), ("endDate", "end"))
            if data.get(field) and re.fullmatch(r'[12][0-9]{3}(?:-(?:0[1-9]|1[0-2]))?', data[field])
            and not (field == "end" and data.get("current"))}


def _portable_uri(value):
    if not isinstance(value, str) or any(character.isspace() for character in value):
        return False
    try:
        return bool(urlsplit(value).scheme)
    except ValueError:
        return False


def _highlights(data):
    return [point['text'] for point in data.get('bullets', [])]


def export_profile(bank: dict) -> dict:
    """Map a tenant-scoped active bank to a portable resume.json.

    Standard fields contain the main wording only. ``meta.jobHunter`` is a
    complete independent copy of basics and active items, preserving every
    app-specific field for the future import mapper.
    """
    basics = bank.get('basics', {})
    resume_basics = {
        'name': basics.get('name', basics.get('display_name', '')),
        'label': basics.get('headline', ''),
        'email': basics.get('email', ''),
        'phone': basics.get('phone', ''),
        'summary': basics.get('summary', ''),
        'location': {'city': basics.get('location', '')},
        'profiles': [],
    }
    for link in basics.get('links', []):
        if isinstance(link, str):
            resume_basics['profiles'].append({'network': '', 'username': '', 'url': link})
        elif isinstance(link, dict) and isinstance(link.get('url'), str):
            resume_basics['profiles'].append({
                'network': link.get('network', link.get('label', '')),
                'username': link.get('username', ''), 'url': link['url'],
            })
    items = [item for item in bank.get('items', []) if item.get('archived_at') is None]
    items = sorted(items, key=lambda item: (item['kind'], item.get('position', 0), str(item['id'])))
    result = {'basics': resume_basics, 'work': [], 'education': [], 'projects': [],
              'skills': [], 'certificates': [], 'awards': [], 'volunteer': []}
    for item in items:
        data = item['data']
        kind = item['kind']
        dates = _dates(data)
        points = _highlights(data)
        if kind == 'experience':
            result['work'].append({'name': data.get('organisation', ''),
                'position': data.get('title', ''), 'location': data.get('location', ''),
                'summary': data.get('summary', ''), 'highlights': points, **dates})
        elif kind == 'education':
            result['education'].append({'institution': data.get('institution', ''),
                'area': data.get('qualification', ''), 'studyType': '',
                'score': data.get('grade', ''), 'courses': points, **dates})
        elif kind == 'project':
            result['projects'].append({'name': data.get('name', ''),
                'description': data.get('summary', ''), 'url': data.get('url', ''),
                'roles': [data['role']] if data.get('role') else [],
                'keywords': deepcopy(data.get('skills', [])), 'highlights': points, **dates})
        elif kind == 'skill':
            result['skills'].append({'name': data.get('name', ''),
                                    'level': data.get('level', ''), 'keywords': []})
        elif kind == 'certification':
            result['certificates'].append({'name': data.get('name', ''),
                'issuer': data.get('issuer', ''), 'url': data.get('url', ''),
                **({'date': dates['startDate']} if dates.get('startDate') else {})})
        elif kind == 'award':
            summary = '\n'.join(part for part in [data.get('summary', ''), *points] if part)
            result['awards'].append({'title': data.get('title', ''),
                'awarder': data.get('awarder', ''), 'summary': summary,
                **({'date': dates['startDate']} if dates.get('startDate') else {})})
        elif kind == 'volunteering':
            result['volunteer'].append({'organization': data.get('organisation', ''),
                'position': data.get('title', ''), 'summary': data.get('summary', ''),
                'highlights': points, **dates})
    # Empty/invalid optional contact fields are not valid JSON Resume formats.
    # Preserve their original values in metadata rather than fabricate values.
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', resume_basics['email']):
        resume_basics.pop('email')
    for row in [*resume_basics['profiles'], *result['projects'], *result['certificates']]:
        if 'url' in row and not _portable_uri(row['url']):
            row.pop('url')
    for certificate in result['certificates']:
        # v1 certificates.date alone requires a full calendar day. Bank dates
        # intentionally have lower precision; the original is retained below.
        certificate.pop('date', None)
    result['meta'] = {'version': 'v1.0.0', 'jobHunter': {
        'schemaVersion': 1, 'bankRevision': bank.get('bank_revision', 0),
        'basics': _json_value(basics), 'items': _json_value(items),
        **({'basicsProvenance': _json_value(bank['basics_provenance'])} if 'basics_provenance' in bank else {}),
    }}
    return result
