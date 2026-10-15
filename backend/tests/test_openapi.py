"""The committed contract must describe the API under test."""
import json
from pathlib import Path
from job_hunter.api.main import app


def test_openapi_contract_is_current():
    candidates = (Path.cwd() / 'contracts/openapi.json', Path(__file__).resolve().parents[2] / 'contracts/openapi.json')
    path = next((path for path in candidates if path.is_file()), None)
    assert path is not None, 'Missing contract: run `make openapi`'
    actual = json.dumps(app.openapi(), sort_keys=True)
    expected = json.dumps(json.loads(path.read_text()), sort_keys=True)
    assert actual == expected, 'OpenAPI contract changed: run `make openapi`'
