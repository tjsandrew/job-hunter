"""The AWS embed worker against real PostgreSQL: pending queries, a full pass, the advisory lock, the time
budget and the ``jobhunter_embedder`` role under forced row-level security.

The worker uses several connections, so these tests run in a THROWAWAY DATABASE (created from the migrations
and dropped afterwards). The live development database is never read or written, and no test embeds real jobs.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from job_hunter.config import settings
from job_hunter.domain.models import Job, Preference, Profile, ProfileVersion, User
from job_hunter.embedding.client import DIMENSIONS, EmbeddingResult
from job_hunter.embedding.db_role import EMBEDDER_ROLE, grant_embedder
from job_hunter.embedding.db_tables import job_embeddings, profile_embeddings
from job_hunter.embedding.pending import confirmed_profile_user_ids, pending_job_ids, touch_job_embeddings
from job_hunter.embedding.job_text import JOB_TEXT_VERSION
from job_hunter.embedding.worker import LOCK_KEY, run_pass

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_INTEGRATION") != "1",
                               reason="set RUN_DB_INTEGRATION=1 against local PostgreSQL")

MODEL = "test/model-a"
SNAPSHOT = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "profile_snapshot_demo.json").read_text("utf-8"))


class FakeEmbedder:
    """Deterministic 512-dimension unit vectors; records every call so tests can see whether the model was used."""

    def __init__(self, model=MODEL, on_call=None):
        self.model, self.calls, self.on_call = model, [], on_call

    def embed(self, texts):
        self.calls.append(list(texts))
        if self.on_call:
            self.on_call()
        vectors = []
        for value in texts:
            seed = int(hashlib.sha256(value.encode()).hexdigest()[:8], 16)
            vector = [0.0] * DIMENSIONS
            vector[seed % DIMENSIONS] = 1.0
            vectors.append(tuple(vector))
        return EmbeddingResult(model=self.model, embeddings=tuple(vectors))


@pytest.fixture(scope="module")
def worker_db():
    owner_url = make_url(settings.migration_database_url or settings.database_url)
    name = "embedtest_" + uuid4().hex[:10]
    admin = create_engine(owner_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"""DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{EMBEDDER_ROLE}') THEN
              CREATE ROLE {EMBEDDER_ROLE} LOGIN PASSWORD '{EMBEDDER_ROLE}' NOSUPERUSER NOBYPASSRLS;
            END IF; END $$"""))
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = owner_url.set(database=name)
    previous = os.environ.get("MIGRATION_DATABASE_URL")
    os.environ["MIGRATION_DATABASE_URL"] = url.render_as_string(hide_password=False)
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if previous is None:
            os.environ.pop("MIGRATION_DATABASE_URL", None)
        else:
            os.environ["MIGRATION_DATABASE_URL"] = previous
    owner = create_engine(url)
    with owner.begin() as connection:
        assert grant_embedder(connection) is True
    # the role's password is the local-development one from infra/local/init-db.sql
    embedder = create_engine(url.set(username=EMBEDDER_ROLE, password=EMBEDDER_ROLE))
    try:
        yield SimpleNamespace(owner=owner, embedder=embedder)
    finally:
        embedder.dispose()
        owner.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def db(worker_db):
    """Start every test from empty jobs, users and embeddings (the throwaway database is shared by the module)."""
    with worker_db.owner.begin() as connection:   # the owner is a superuser, so row-level security does not apply
        connection.execute(text("TRUNCATE job_embeddings, profile_embeddings, profile_versions, preferences, "
                                "profiles, users, jobs CASCADE"))
    return worker_db


def add_jobs(db, count, *, prefix="Role"):
    ids = []
    with Session(db.owner) as session:
        for index in range(count):
            job = Job(title=f"{prefix} {index}", description=f"Build and run service number {index}. " * 5,
                      status="open", source="embedtest", url=f"https://example.test/{uuid4().hex}")
            session.add(job)
            session.flush()
            ids.append(job.id)
        session.commit()
    return sorted(ids)


def add_user_with_profile(db, name="Casey"):
    user_id = uuid4()
    with Session(db.owner) as session:
        session.add(User(id=user_id, auth_subject=str(uuid4()), display_name=name))
        session.flush()
        session.add(Profile(user_id=user_id, draft={}, confirmed_revision=1))
        session.add(ProfileVersion(user_id=user_id, revision=1, data=SNAPSHOT, content_hash=uuid4().hex))
        session.add(Preference(user_id=user_id, data={"target_roles": ["Backend Engineer"]}))
        session.commit()
    return user_id


def embedding_rows(db):
    with db.owner.connect() as connection:
        return connection.execute(select(job_embeddings.c.job_id, job_embeddings.c.status, job_embeddings.c.model,
                                         job_embeddings.c.updated_at)).all()


def pass_args(**overrides):
    args = dict(model=MODEL, deadline=10 ** 9, batch_size=3, clock=lambda: 0.0)
    args.update(overrides)
    return args


def pending(db, **kwargs):
    with Session(db.embedder) as session:
        return pending_job_ids(session, text_version=JOB_TEXT_VERSION, model=kwargs.pop("model", MODEL),
                               limit=kwargs.pop("limit", 100), **kwargs)


# ---- pending queries ------------------------------------------------------------------------------------

def test_pending_follows_the_state_of_each_job(db):
    ids = add_jobs(db, 3)
    assert pending(db) == ids                                          # nothing embedded yet
    embedder = FakeEmbedder()
    run_pass(db.embedder, embedder, **pass_args())
    assert pending(db) == []                                           # all current
    assert pending(db, model="test/model-b") == ids                    # a different model counts as out of date
    assert pending(db, after_id=ids[0]) == []                          # the cursor only moves forward
    assert pending(db, everything=True) == ids                         # a forced run takes every open job


def test_a_closed_job_is_never_pending(db):
    ids = add_jobs(db, 2)
    with db.owner.begin() as connection:
        connection.execute(text("UPDATE jobs SET status='closed' WHERE id = :id"), {"id": ids[0]})
    assert pending(db) == [ids[1]]


def test_an_updated_job_is_pending_until_it_is_checked(db):
    (job_id,) = add_jobs(db, 1)
    run_pass(db.embedder, FakeEmbedder(), **pass_args())
    with db.owner.begin() as connection:   # the job row changed after its vector was stored
        connection.execute(text("UPDATE job_embeddings SET updated_at = now() - interval '1 hour'"))
        connection.execute(text("UPDATE jobs SET updated_at = now() - interval '30 minutes' WHERE id = :id"), {"id": job_id})
    assert pending(db) == [job_id]
    with Session(db.embedder) as session:   # the pipeline finds the text unchanged; the row is touched so it stops being a candidate
        touch_job_embeddings(session, [job_id], JOB_TEXT_VERSION)
        session.commit()
    assert pending(db) == []


def test_failed_rows_wait_for_the_backoff_and_no_content_rows_for_a_change(db):
    failed, no_content = add_jobs(db, 2)
    with db.owner.begin() as connection:
        for job_id, status, reason in ((failed, "failed", "boom"), (no_content, "no_content", "empty")):
            connection.execute(text("""INSERT INTO job_embeddings (job_id, text_version, status, reason)
                                       VALUES (:id, :tv, :status, :reason)"""),
                               {"id": job_id, "tv": JOB_TEXT_VERSION, "status": status, "reason": reason})
        # both jobs were last updated before their rows were written
        connection.execute(text("UPDATE jobs SET updated_at = now() - interval '1 day'"))
    assert pending(db) == []                                           # fresh failure: not retried yet; no_content: not retried
    with db.owner.begin() as connection:
        connection.execute(text("UPDATE job_embeddings SET updated_at = now() - interval '2 hours'"))
    assert pending(db) == [failed]                                     # the failed row is retried after the back-off only
    with db.owner.begin() as connection:
        connection.execute(text("UPDATE jobs SET updated_at = now() WHERE id = :id"), {"id": no_content})
    assert sorted(pending(db)) == sorted([failed, no_content])         # a changed job is retried whatever its status


# ---- a full pass ----------------------------------------------------------------------------------------

def test_a_pass_embeds_jobs_and_profiles_and_the_next_pass_does_nothing(db):
    ids = add_jobs(db, 5)
    user_a, user_b = add_user_with_profile(db, "A"), add_user_with_profile(db, "B")
    embedder = FakeEmbedder()
    result = run_pass(db.embedder, embedder, **pass_args())
    assert result.busy is False and result.remaining is False
    assert result.jobs == {"ready": 5} and result.profiles == {"ready": 2} and result.progress == 7
    assert sorted(row.job_id for row in embedding_rows(db)) == ids
    with db.owner.connect() as connection:
        owners = connection.execute(select(profile_embeddings.c.user_id, profile_embeddings.c.model,
                                           profile_embeddings.c.status)).all()
    assert {row.user_id for row in owners} == {user_a, user_b}
    assert {row.model for row in owners} == {MODEL} and {row.status for row in owners} == {"ready"}

    calls_before = len(embedder.calls)
    again = run_pass(db.embedder, embedder, **pass_args())
    assert again.progress == 0 and again.jobs == {} and again.profiles == {"unchanged": 2}
    assert len(embedder.calls) == calls_before       # nothing pending: the model was never called


def test_a_pass_with_nothing_to_do_never_calls_the_embedder(db):
    embedder = FakeEmbedder()
    result = run_pass(db.embedder, embedder, **pass_args())
    assert result.progress == 0 and embedder.calls == []


def test_a_changed_job_and_a_changed_model_are_re_embedded(db):
    ids = add_jobs(db, 2)
    run_pass(db.embedder, FakeEmbedder(), **pass_args())
    with db.owner.begin() as connection:   # new text, so a new hash, written after the vector was stored
        connection.execute(text("UPDATE job_embeddings SET updated_at = now() - interval '1 hour'"))
        connection.execute(text("UPDATE jobs SET description = 'Completely different duties.', "
                                "updated_at = now() - interval '30 minutes' WHERE id = :id"), {"id": ids[0]})
    changed = FakeEmbedder()
    result = run_pass(db.embedder, changed, **pass_args())
    assert result.jobs.get("ready") == 1 and len(changed.calls) == 1
    swapped = FakeEmbedder(model="test/model-b")
    result = run_pass(db.embedder, swapped, **pass_args(model="test/model-b"))
    assert result.jobs == {"ready": 2}
    assert {row.model for row in embedding_rows(db)} == {"test/model-b"}


def test_a_forced_pass_re_embeds_everything_once(db):
    add_jobs(db, 4)
    run_pass(db.embedder, FakeEmbedder(), **pass_args())
    forced = FakeEmbedder()
    result = run_pass(db.embedder, forced, **pass_args(force=True))
    assert result.jobs == {"ready": 4} and sum(len(call) for call in forced.calls) == 4   # one sweep, not a loop


def test_a_job_that_stays_a_candidate_does_not_make_the_pass_loop(db):
    (job_id,) = add_jobs(db, 1)
    run_pass(db.embedder, FakeEmbedder(), **pass_args())
    with db.owner.begin() as connection:   # a timestamp in the future (clock skew) keeps it a candidate whatever the worker does
        connection.execute(text("UPDATE jobs SET updated_at = now() + interval '1 hour' WHERE id = :id"), {"id": job_id})
    ticks = iter(range(100_000))
    embedder = FakeEmbedder()
    result = run_pass(db.embedder, embedder, **pass_args(deadline=500.0, clock=lambda: float(next(ticks))))
    assert result.jobs == {"unchanged": 1} and result.progress == 0 and embedder.calls == []   # looked at once, then stopped


# ---- locking and the time budget -------------------------------------------------------------------------

def test_a_second_runner_gives_way_while_the_lock_is_held(db):
    add_jobs(db, 2)
    holder = db.owner.connect()
    try:
        holder.execute(text("SELECT pg_advisory_lock(:key)"), {"key": LOCK_KEY})
        embedder = FakeEmbedder()
        result = run_pass(db.embedder, embedder, **pass_args())
        assert result.busy is True and embedder.calls == []
    finally:
        holder.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
        holder.close()
    assert run_pass(db.embedder, FakeEmbedder(), **pass_args()).jobs == {"ready": 2}    # and the lock is free again afterwards


def test_the_pass_stops_before_the_deadline_and_says_work_remains(db):
    add_jobs(db, 6)
    state = {"now": 0.0}
    embedder = FakeEmbedder(on_call=lambda: state.__setitem__("now", state["now"] + 10.0))   # every batch takes 10 "seconds"
    result = run_pass(db.embedder, embedder, **pass_args(batch_size=2, deadline=25.0, clock=lambda: state["now"]))
    assert result.remaining is True and result.progress == 4 and result.batches == 2      # a third batch would not fit
    assert len(pending(db)) == 2


# ---- the role under row-level security -------------------------------------------------------------------

def test_the_role_lists_confirmed_profiles_across_users_but_nothing_else_is_open(db):
    user_a, user_b = add_user_with_profile(db, "A"), add_user_with_profile(db, "B")
    with Session(db.embedder) as session:
        assert set(confirmed_profile_user_ids(session)) == {user_a, user_b}       # the one extra read-only policy
        assert session.scalar(select(func.count()).select_from(ProfileVersion)) == 0   # versions stay behind the per-user policy
        assert session.scalar(select(func.count()).select_from(Preference)) == 0
        session.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_a)})
        assert session.scalar(select(func.count()).select_from(ProfileVersion)) == 1   # with the user's context: only that user's
        session.rollback()


def test_the_role_cannot_touch_anything_it_was_not_granted(db):
    user_id = add_user_with_profile(db)
    for statement in ("SELECT * FROM documents", "DELETE FROM jobs", "UPDATE profiles SET revision = 99",
                      "INSERT INTO users (id, auth_subject, display_name, plan) VALUES (gen_random_uuid(), 'x', 'x', 'free')"):
        with Session(db.embedder) as session:
            with pytest.raises(DBAPIError):
                session.execute(text(statement))
            session.rollback()
    with Session(db.embedder) as session:   # even its own tables: a write for a user needs that user's context
        with pytest.raises(DBAPIError):
            session.execute(text("""INSERT INTO profile_embeddings (user_id, profile_version_id, text_version, status)
                                    VALUES (:u, gen_random_uuid(), 'x', 'pending')"""), {"u": user_id})
        session.rollback()


def test_grants_are_idempotent(db):
    with db.owner.begin() as connection:
        assert grant_embedder(connection) is True
        assert grant_embedder(connection) is True
        policies = connection.execute(text("SELECT count(*) FROM pg_policies WHERE policyname = 'embedder_list_users'")).scalar()
    assert policies == 1
