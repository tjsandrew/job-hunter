"""Portable JSON Resume fields and lossless profile-bank metadata."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from uuid import UUID

from job_hunter.demo import PROFILE, PROFILE_ITEMS
from job_hunter.profile_bank.export import export_profile


def test_empty_export_has_json_resume_shape():
    exported = export_profile({'basics': {}, 'items': [], 'bank_revision': 0})
    assert exported['meta']['version'] == 'v1.0.0'
    assert isinstance(exported['basics']['location'], dict)
    assert isinstance(exported['basics']['profiles'], list)
    assert exported['basics']['name'] == ''
    for field in ('work', 'education', 'projects', 'skills', 'certificates', 'awards', 'volunteer'):
        assert exported[field] == []
    assert json.loads(json.dumps(exported)) == exported


def test_demo_export_preserves_every_extra_in_metadata():
    bank = {'basics': deepcopy(PROFILE), 'items': deepcopy(PROFILE_ITEMS), 'bank_revision': 9}
    positions = {}
    for index, item in enumerate(bank['items']):
        item['id'] = str(UUID(int=index + 1))
        item['position'] = positions.get(item['kind'], 0)
        positions[item['kind']] = item['position'] + 1
        item.setdefault('tags', [])
    experience = next(item for item in bank['items'] if item['kind'] == 'experience')
    project = next(item for item in bank['items'] if item['kind'] == 'project')
    project['parent_id'] = experience['id']
    experience['data']['bullets'][0]['provenance'] = {
        'origin': 'import', 'import_id': 'fictional-import',
        'evidence': {'source_sha256': 'a' * 64, 'page': 1, 'text': 'Original excerpt'},
    }
    experience['created_at'] = datetime(2026, 10, 14, tzinfo=timezone.utc)
    before = deepcopy(bank)
    exported = export_profile(bank)
    restored = json.loads(json.dumps(exported))['meta']['jobHunter']
    assert restored['schemaVersion'] == 1 and restored['bankRevision'] == 9
    assert restored['basics'] == PROFILE
    restored_items = {item['id']: item for item in restored['items']}
    for item in bank['items']:
        assert restored_items[item['id']]['data'] == item['data']
        assert restored_items[item['id']]['tags'] == item['tags']
    assert restored_items[project['id']]['parent_id'] == experience['id']
    assert any(item['kind'] == 'custom' for item in restored['items'])
    main_points = [point['text'] for point in experience['data']['bullets']]
    assert exported['work'][0]['highlights'] == main_points
    assert 'alternatives' not in exported['work'][0]
    assert exported['basics']['label'] == PROFILE['headline']
    assert exported['work'][0]['startDate'] == '2023'
    assert 'endDate' not in exported['work'][0]
    assert bank == before


def test_export_standard_kinds_and_dates():
    basics = {'name': 'Fictional Candidate', 'location': 'Fictional City',
              'links': ['https://example.invalid', {'label': 'Portfolio', 'url': 'https://example.invalid/work'}]}
    items = [
        {'id': str(i), 'kind': kind, 'position': 0, 'data': data}
        for i, (kind, data) in enumerate([
            ('education', {'qualification': 'BSc CS', 'institution': 'Example University', 'start': '2018-08', 'end': '2022-05', 'grade': 'Distinction', 'bullets': [{'text': 'Databases'}]}),
            ('certification', {'name': 'Example Certificate', 'issuer': 'Example Body', 'start': '2024'}),
            ('award', {'title': 'Example Award', 'awarder': 'Example Body', 'start': '2025', 'summary': 'Recognition', 'bullets': [{'text': 'Led a team'}]}),
            ('volunteering', {'title': 'Mentor', 'organisation': 'Example Charity', 'current': True, 'start': '2023', 'bullets': [{'text': 'Mentored peers'}]}),
            ('custom', {'title': 'Fun facts', 'bullets': [{'text': 'Builds board games'}]}),
        ])
    ]
    result = export_profile({'basics': basics, 'items': items})
    assert result['education'][0]['courses'] == ['Databases']
    assert result['education'][0]['endDate'] == '2022-05'
    assert 'date' not in result['certificates'][0]
    certificate = next(item for item in result['meta']['jobHunter']['items'] if item['kind'] == 'certification')
    assert certificate['data']['start'] == '2024'
    assert result['awards'][0]['summary'] == 'Recognition\nLed a team'
    assert result['volunteer'][0]['highlights'] == ['Mentored peers']
    assert len(result['basics']['profiles']) == 2
    assert len(result['meta']['jobHunter']['items']) == 5


def test_export_archived_items_excluded_and_uuid_json_safe():
    item_id = UUID('11111111-1111-1111-1111-111111111111')
    result = export_profile({'items': [
        {'id': item_id, 'kind': 'skill', 'data': {'name': 'Python'}},
        {'id': 'archived', 'kind': 'skill', 'data': {'name': 'SQL'}, 'archived_at': '2026-10-14'},
    ]})
    assert result['skills'] == [{'name': 'Python', 'level': '', 'keywords': []}]
    assert result['meta']['jobHunter']['items'][0]['id'] == str(item_id)


def test_exports_match_pinned_json_resume_v1_schema():
    """Check every constraint used by the pinned schema, without new dependencies."""
    from pathlib import Path
    from datetime import date
    from urllib.parse import urlsplit
    import re

    schema = json.loads((Path(__file__).parent / 'fixtures/json_resume_v1_schema.json').read_text())

    def validate(value, rule):
        if '$ref' in rule:
            target = schema
            for key in rule['$ref'][2:].split('/'):
                target = target[key]
            return validate(value, target)
        expected = {'object': dict, 'array': list, 'string': str}[rule['type']]
        assert isinstance(value, expected), (rule, value)
        if isinstance(value, dict):
            properties = rule.get('properties', {})
            if rule.get('additionalProperties') is False:
                assert set(value) <= set(properties)
            for key, child in value.items():
                if key in properties:
                    validate(child, properties[key])
        elif isinstance(value, list):
            for child in value:
                validate(child, rule['items'])
        else:
            if 'pattern' in rule:
                assert re.fullmatch(rule['pattern'], value)
            if rule.get('format') == 'email':
                assert re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value)
            if rule.get('format') == 'uri':
                assert urlsplit(value).scheme and not any(c.isspace() for c in value)
            if rule.get('format') == 'date':
                assert date.fromisoformat(value).isoformat() == value

    for bank in ({'basics': {}, 'items': []}, {'basics': PROFILE, 'items': [
        {**item, 'id': str(index), 'position': index} for index, item in enumerate(PROFILE_ITEMS)
    ]}):
        validate(export_profile(bank), schema)


def test_export_retains_unportable_contact_values_in_metadata():
    basics = {'email': 'not an email', 'links': ['https://[broken', 'https://example.invalid/a b']}
    item = {'id': 'future', 'kind': 'experience', 'data': {'title': 'Engineer', 'start': '3001'}}
    exported = export_profile({'basics': basics, 'items': [item]})
    assert 'email' not in exported['basics']
    assert all('url' not in profile for profile in exported['basics']['profiles'])
    assert 'startDate' not in exported['work'][0]
    assert exported['meta']['jobHunter']['basics'] == basics
    assert exported['meta']['jobHunter']['items'][0] == item
