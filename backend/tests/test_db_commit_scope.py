"""The request transaction must commit before the response is sent.

FastAPI exits default ("request") scoped yield dependencies only after sending
the response, so get_db's commit could land after a client already saw 201. A
create-then-read (export, then download) then raced to a 404.
"""
from fastapi.routing import APIRoute

from job_hunter.api.main import app, db_for


def _routes(routes):
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):  # Included routers are nested.
            yield from _routes(route.original_router.routes)
        elif hasattr(route, "routes"):
            yield from _routes(route.routes)


def _dependencies(dependant):
    for dependency in dependant.dependencies:
        yield dependency
        yield from _dependencies(dependency)


def test_every_database_session_commits_before_the_response():
    uses = [(route.path, dependency.scope) for route in _routes(app.routes)
            for dependency in _dependencies(route.dependant) if dependency.call is db_for]
    # Guards against the walk silently missing the profile-bank and resume routers.
    assert len(uses) >= 50
    assert [path for path, scope in uses if scope != "function"] == []
