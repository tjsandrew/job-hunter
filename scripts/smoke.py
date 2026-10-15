"""Exercise the running local API with real HTTP and persistence, without paid services."""
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = os.environ.get('API_URL', 'http://localhost:8000/v1')

def call(path, method='GET', body=None, user='alice', expected=200):
    binary = isinstance(body, bytes)
    req = Request(BASE + path, data=body if binary else None if body is None else json.dumps(body).encode(),
                  headers={'X-Dev-User': user, 'Content-Type': 'application/pdf' if binary else 'application/json'}, method=method)
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
    casey = call('/me', user='casey')
    assert alice != casey
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
    call(path, user='casey', expected=404)
    call(path, 'PATCH', {'title': 'Should conflict', 'expected_revision': 0}, expected=409)
    preview = call(path + '/preview.pdf')
    assert preview.startswith(b'%PDF')
    call(path + '/exports', 'POST', expected=409)
    call(path + '/review', 'POST', {'expected_revision': doc['revision']})
    export = call(path + '/exports', 'POST', expected=201)
    assert export['export_id']
    assert call('/exports/' + export['export_id']).startswith(b'%PDF')
    call('/exports/' + export['export_id'], user='casey', expected=404)
    upload = call('/uploads', 'POST', {'filename': 'synthetic-resume.pdf',
                  'content_type': 'application/pdf', 'size_bytes': len(preview)}, expected=201)
    upload_path = '/uploads/' + upload['upload_id']
    call(upload_path + '/content', 'PUT', preview, user='casey', expected=404)
    parsed = call(upload_path + '/content', 'PUT', preview)
    assert parsed['status'] == 'ready_for_review', parsed
    candidate = call(upload_path)
    assert 'Synthetic Applicant' in candidate['extracted_text']
    call(upload_path, user='casey', expected=404)
    call(upload_path + '/content', 'PUT', preview, expected=409)
    print('PASS: health, identities, recommendations, persistence, owner isolation, revision conflict, PDF preview, review-gated export, immutable upload and candidate text extraction')

if __name__ == '__main__':
    main()
