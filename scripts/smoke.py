"""Exercise the running local API with real HTTP and persistence, without paid services."""
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = os.environ.get('API_URL', 'http://localhost:8000/v1')

def call(path, method='GET', body=None, user='alice', expected=200):
    req = Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                  headers={'X-Dev-User': user, 'Content-Type': 'application/json'}, method=method)
    try:
        response = urlopen(req, timeout=20)
    except HTTPError as error:
        response = error
    raw = response.read()
    assert response.status == expected, (method, path, response.status, raw[:500])
    if 'application/json' in response.headers.get('Content-Type', ''):
        return json.loads(raw)
    return raw


def main():
    call('/health')
    alice = call('/me')
    bob = call('/me', user='bob')
    assert alice != bob
    jobs = call('/recommendations')
    assert isinstance(jobs['items'], list)
    doc = call('/documents', 'POST', {
        'title': 'Synthetic integration test resume', 'template': 'classic',
        'content': {'name': 'Synthetic Applicant', 'email': 'test@example.invalid',
                    'phone': '', 'location': 'Singapore', 'summary': 'Integration test only.',
                    'sections': [{'id': 'experience', 'title': 'Experience', 'entries': [
                        {'id': 'entry-1', 'heading': 'Test role', 'subheading': 'Example',
                         'dates': '2025–2026', 'bullets': ['Built a tested application.']}]}]},
        'layout': {'font_size': 11, 'margin': 18}}, expected=201)
    path = '/documents/' + doc['id']
    call(path, user='bob', expected=404)
    call(path, 'PATCH', {'title': 'Should conflict', 'expected_revision': 0}, expected=409)
    preview = call(path + '/preview.pdf')
    assert preview.startswith(b'%PDF')
    call(path + '/review', 'POST', {'expected_revision': doc['revision']})
    export = call(path + '/exports', 'POST')
    assert export['export_id']
    call('/exports/' + export['export_id'], user='bob', expected=404)
    print('PASS: health, identities, recommendations, persistence, owner isolation, revision conflict, PDF preview and reviewed export')

if __name__ == '__main__':
    main()
