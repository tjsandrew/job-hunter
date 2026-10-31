"""Migration 0012 and the database-backed embedding stores, run as a non-owner under forced row-level security.

Everything happens in one transaction that is rolled back (throwaway schema and role), like the other
integration tests, so the live database is never changed.
"""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from job_hunter.config import settings
from job_hunter.domain.models import Base, Job, ProfileVersion, User
from job_hunter.embedding import (
    JOB_TEXT_VERSION, STATUS_FAILED, STATUS_READY, STATUS_UNCHANGED, EmbeddingRecord, EmbeddingResult, JobEmbedRequest, JobTextInput,
    ProfileEmbedRequest, embed_jobs, embed_profile)
from job_hunter.embedding.db_store import DbJobEmbeddingStore, DbProfileEmbeddingStore
from job_hunter.seniority import classify_seniority

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_INTEGRATION") != "1",
                               reason="set RUN_DB_INTEGRATION=1 against local PostgreSQL")

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"
NEW_TABLES = {"job_embeddings", "profile_embeddings", "job_match_features"}
SENIORITY_COLUMNS = {"seniority", "seniority_source", "seniority_evidence"}


def load_migration(file="0012_embedding_tables.py"):
    spec = importlib.util.spec_from_file_location("migration_" + file[:4], VERSIONS / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(connection, function):
    with Operations.context(MigrationContext.configure(connection)):
        function()


def tables(connection, schema):
    rows = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname=:s"), {"s": schema}).scalars()
    return set(rows)


def columns(connection, schema, names):
    rows = connection.execute(text("""SELECT table_name, column_name, data_type FROM information_schema.columns
                                      WHERE table_schema=:s AND table_name = ANY(:n) ORDER BY 1, 2"""),
                              {"s": schema, "n": list(names)}).all()
    return [tuple(r) for r in rows]


def set_user(connection, user_id):
    connection.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})


@pytest.fixture
def schema_conn():
    """Owner connection with the app schema created from the models, before migration 0012 is applied."""
    engine = create_engine(settings.migration_database_url or settings.database_url)
    suffix = uuid4().hex
    schema, role = "emb_" + suffix, "emb_writer_" + suffix
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS'))
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            Base.metadata.create_all(connection, checkfirst=False)
            connection.execute(text("ALTER TABLE profile_versions ENABLE ROW LEVEL SECURITY"))
            connection.execute(text("ALTER TABLE profile_versions FORCE ROW LEVEL SECURITY"))
            connection.execute(text("""CREATE POLICY tenant_isolation ON profile_versions
                USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
                WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)"""))
            yield SimpleNamespace(connection=connection, schema=schema, role=role)
        finally:
            transaction.rollback()
    engine.dispose()


@pytest.fixture
def db(schema_conn):
    connection, schema, role = schema_conn.connection, schema_conn.schema, schema_conn.role
    run(connection, load_migration().upgrade)
    connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
    connection.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))
    connection.execute(text(f'SET LOCAL ROLE "{role}"'))
    assert connection.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")).one() == (False, False)
    session = Session(bind=connection)
    user_a, user_b = User(auth_subject="a-" + uuid4().hex, display_name="A"), User(auth_subject="b-" + uuid4().hex, display_name="B")
    job = Job(title="Backend Engineer", description="x")
    session.add_all([user_a, user_b, job])
    session.flush()
    set_user(connection, user_a.id)
    version_a = ProfileVersion(user_id=user_a.id, revision=1, data={}, content_hash="h" * 64)
    session.add(version_a)
    session.flush()
    yield SimpleNamespace(connection=connection, session=session, user_a=user_a.id, user_b=user_b.id,
                          job_id=job.id, version_a=version_a.id, schema=schema)


def ready(version="job-v1", model="m", hash_="a" * 64, value=1.0):
    return EmbeddingRecord(status=STATUS_READY, model=model, dimensions=512, text_version=version,
                           input_hash=hash_, vector=tuple([value] + [0.0] * 511))


class FakeEmbedder:
    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return EmbeddingResult(model="fake-model", embeddings=tuple(tuple([1.0] + [0.0] * 511) for _ in texts))


# ---- migration ----------------------------------------------------------------------------------

def test_migration_adds_only_new_tables_changes_nothing_else_and_reverses(schema_conn):
    connection, schema = schema_conn.connection, schema_conn.schema
    existing_before = tables(connection, schema)
    watched = ("jobs", "profile_versions", "profiles", "users")
    columns_before = columns(connection, schema, watched)
    migration = load_migration()

    run(connection, migration.upgrade)
    assert tables(connection, schema) - existing_before == NEW_TABLES
    assert columns(connection, schema, watched) == columns_before                 # no existing column touched
    assert connection.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                                   "WHERE relname='profile_embeddings' AND relnamespace=(SELECT oid FROM pg_namespace WHERE nspname=:s)"),
                              {"s": schema}).one() == (True, True)
    run(connection, migration.upgrade)                                             # idempotent (IF NOT EXISTS)

    run(connection, migration.downgrade)
    assert tables(connection, schema) == existing_before
    run(connection, migration.upgrade)
    assert tables(connection, schema) - existing_before == NEW_TABLES


def test_migration_0013_adds_the_job_seniority_columns_and_reverses(schema_conn):
    connection, schema = schema_conn.connection, schema_conn.schema
    migration = load_migration("0013_job_seniority.py")
    assert migration.down_revision == "0012_embedding_tables"

    def job_columns():
        return {row[1]: row[2] for row in columns(connection, schema, ["jobs"])}

    run(connection, load_migration().upgrade)
    assert "job_match_features" in tables(connection, schema)
    for name in SENIORITY_COLUMNS:           # the test schema is built from the models, which already have them
        connection.execute(text(f"ALTER TABLE jobs DROP COLUMN {name}"))
    assert not SENIORITY_COLUMNS & set(job_columns())
    run(connection, migration.upgrade)
    found = job_columns()
    assert SENIORITY_COLUMNS <= set(found) and found["seniority"] == "json"
    assert found["seniority_source"] == found["seniority_evidence"] == "character varying"
    assert "job_match_features" not in tables(connection, schema)
    run(connection, migration.upgrade)                                               # idempotent (IF NOT EXISTS)
    run(connection, migration.downgrade)
    assert not SENIORITY_COLUMNS & set(job_columns())
    assert "job_match_features" in tables(connection, schema)
    run(connection, migration.upgrade)
    assert SENIORITY_COLUMNS <= set(job_columns())
    assert "job_match_features" not in tables(connection, schema)


def test_migration_0013_preserves_stated_seniority_before_retiring_features(schema_conn):
    connection = schema_conn.connection
    run(connection, load_migration().upgrade)
    job = Job(title="Senior Engineer", description="x")
    session = Session(bind=connection)
    session.add(job)
    session.flush()
    connection.execute(text("""INSERT INTO job_match_features (job_id, feature_version, features)
        VALUES (:job_id, 'features-v2', CAST(:features AS jsonb))"""),
        {"job_id": job.id, "features": '{"seniority_levels": ["junior"], "seniority_source": "stated"}'})
    run(connection, load_migration("0013_job_seniority.py").upgrade)
    values = connection.execute(text("SELECT seniority, seniority_source FROM jobs WHERE id=:job_id"),
                                {"job_id": job.id}).one()
    assert values.seniority == ["junior"] and values.seniority_source == "stated"
    assert "job_match_features" not in tables(connection, schema_conn.schema)


# ---- job store ----------------------------------------------------------------------------------

def test_job_store_saves_updates_and_keeps_formats_side_by_side(db):
    store = DbJobEmbeddingStore(db.session)
    key = str(db.job_id)
    assert store.get_state(key, "job-v1") is None
    store.save(key, ready())
    state = store.get_state(key, "job-v1")
    assert (state.status, state.model, state.text_version, state.input_hash) == ("ready", "m", "job-v1", "a" * 64)

    store.save(key, ready(model="m2", hash_="b" * 64))                    # same format: row replaced
    store.save(key, ready(version="job-v2"))                              # new format: second row
    assert store.get_state(key, "job-v1").model == "m2" and store.get_state(key, "job-v1").input_hash == "b" * 64
    assert store.get_state(key, "job-v2").status == "ready"
    count = db.connection.execute(text("SELECT count(*) FROM job_embeddings WHERE job_id=:j"), {"j": db.job_id}).scalar_one()
    assert count == 2
    first = db.connection.execute(text("SELECT embedding::text FROM job_embeddings WHERE job_id=:j AND text_version='job-v1'"),
                                  {"j": db.job_id}).scalar_one()
    assert first.startswith("[1,0,0")


def test_pending_rows_have_no_vector_and_the_database_enforces_that(db):
    store = DbJobEmbeddingStore(db.session)
    key = str(db.job_id)
    store.save(key, EmbeddingRecord(status="pending", model=None, dimensions=None, text_version="job-v1",
                                    input_hash="c" * 64, vector=None, reason="embedding service unavailable"))
    assert store.get_state(key, "job-v1").status == "pending"
    store.save(key, ready())                                              # pending -> ready replaces it
    assert store.get_state(key, "job-v1").status == "ready"
    with pytest.raises(IntegrityError):                                    # ready without a vector is rejected
        store.save(key, EmbeddingRecord(status="ready", model="m", dimensions=512, text_version="job-v1",
                                        input_hash="d" * 64, vector=None))
    with pytest.raises(IntegrityError):                                    # a vector on a pending row is rejected
        store.save(key, EmbeddingRecord(status="pending", model="m", dimensions=512, text_version="job-v1",
                                        input_hash="d" * 64, vector=tuple([1.0] + [0.0] * 511)))
    assert store.get_state(key, "job-v1").status == "ready"               # savepoints kept the earlier row intact
    assert db.connection.execute(text("SELECT 1")).scalar_one() == 1       # and the transaction is still usable


def test_deleting_a_job_removes_its_embeddings(db):
    store = DbJobEmbeddingStore(db.session)
    store.save(str(db.job_id), ready())
    db.connection.execute(text("DELETE FROM jobs WHERE id=:j"), {"j": db.job_id})
    assert db.connection.execute(text("SELECT count(*) FROM job_embeddings")).scalar_one() == 0


def test_bad_keys_are_rejected(db):
    store = DbJobEmbeddingStore(db.session)
    with pytest.raises(ValueError):
        store.get_state("not-a-uuid", "job-v1")


# ---- profile store ------------------------------------------------------------------------------

def test_profile_embeddings_are_private_to_their_owner(db):
    store = DbProfileEmbeddingStore(db.session)
    key = str(db.version_a)
    store.save(key, ready(version="profile-v2"))                           # user A (context already set)
    assert store.get_state(key, "profile-v2").status == "ready"
    owner = db.connection.execute(text("SELECT user_id FROM profile_embeddings")).scalar_one()
    assert owner == db.user_a                                              # owner taken from the profile version

    set_user(db.connection, db.user_b)                                     # now acting as user B
    assert store.get_state(key, "profile-v2") is None
    assert db.connection.execute(text("SELECT count(*) FROM profile_embeddings")).scalar_one() == 0
    with pytest.raises(LookupError):
        store.save(key, ready(version="profile-v2", value=0.5))            # cannot write for A's profile version

    set_user(db.connection, db.user_a)                                     # back to A: nothing was changed
    assert db.connection.execute(text("SELECT embedding::text FROM profile_embeddings")).scalar_one().startswith("[1,0")


# ---- the embedding functions on top of the database stores --------------------------------------

def test_embedding_functions_work_end_to_end_and_survive_one_bad_item(db):
    embedder, store = FakeEmbedder(), DbJobEmbeddingStore(db.session)
    description = "Responsibilities\n" + "Build and run payment APIs for the platform team. " * 6
    good = JobEmbedRequest(job_id=str(db.job_id), job=JobTextInput(title="Backend Engineer", description=description))
    bad = JobEmbedRequest(job_id=str(uuid4()),     # not a real job: foreign key fails
                          job=JobTextInput(title="Data Analyst", description=description))
    outcomes = embed_jobs([bad, good], embedder=embedder, store=store)
    assert [o.status for o in outcomes] == [STATUS_FAILED, STATUS_READY]
    assert outcomes[0].reason == "storage error: IntegrityError"
    assert store.get_state(str(db.job_id), JOB_TEXT_VERSION).status == "ready"

    again = embed_jobs([good], embedder=embedder, store=store, expected_model="fake-model")
    assert again[0].status == STATUS_UNCHANGED and len(embedder.calls) == 1


def test_profile_function_with_the_database_store(db):
    embedder, store = FakeEmbedder(), DbProfileEmbeddingStore(db.session)
    request = ProfileEmbedRequest(profile_version_id=str(db.version_a),
                                  snapshot={"headline": "Junior backend engineer", "skills": ["Python"]},
                                  target_roles=["Backend Engineer"])
    assert embed_profile(request, embedder=embedder, store=store).status == STATUS_READY
    assert embed_profile(request, embedder=embedder, store=store).status == STATUS_UNCHANGED
    assert store.get_state(str(db.version_a), "profile-v2").model == "fake-model"
    set_user(db.connection, db.user_b)
    outcome = embed_profile(request, embedder=embedder, store=store)       # another user cannot reach this version
    assert outcome.status == STATUS_FAILED and outcome.reason == "storage error: LookupError"


# ---- retrieval on the database tables -----------------------------------------------------------

def v(*head):
    return tuple(list(head) + [0.0] * (512 - len(head)))


def test_recommend_for_profile_checks_first_then_ranks_and_never_mixes_models(db):
    from job_hunter.embedding.db_retrieval import recommend_for_profile

    def job(title, category, location="Singapore", status="open"):
        # what ingestion stores on the job row: the role family and the levels named by the title
        item = Job(title=title, description="x", category=category, seniority=classify_seniority(title)[0],
                   location=location, status=status)
        db.session.add(item)
        db.session.flush()
        return str(item.id)

    jobs = SimpleNamespace(
        good=job("Backend Engineer, Payments", "engineering"),
        ok2=job("Platform Engineer", "engineering"),
        recruiter=job("Technical Recruiter", "people"),
        principal=job("Principal Engineer", "engineering"),
        closed=job("Software Engineer", "engineering", status="closed"),
        london=job("Software Engineer", "engineering", location="London"),
        pending=job("DevOps Engineer", "engineering"),
        unembedded=job("QA Engineer", "engineering"),
        other_model=job("Data Platform Engineer", "engineering"),
    )
    job_store, profile_store = DbJobEmbeddingStore(db.session), DbProfileEmbeddingStore(db.session)
    vectors = {"good": v(1.0), "ok2": v(0.6, 0.8), "recruiter": v(0.99, 0.1), "principal": v(0.98, 0.2),
               "closed": v(1.0), "london": v(1.0), "other_model": v(1.0)}
    for name, vector in vectors.items():
        job_store.save(getattr(jobs, name), EmbeddingRecord(
            status="ready", model="other" if name == "other_model" else "m", dimensions=512,
            text_version=JOB_TEXT_VERSION, input_hash="h" * 64, vector=vector))
    job_store.save(jobs.pending, EmbeddingRecord(status="pending", model=None, dimensions=None, text_version=JOB_TEXT_VERSION,
                                                 input_hash="h" * 64, vector=None))
    profile_store.save(str(db.version_a), EmbeddingRecord(status="ready", model="m", dimensions=512,
                                                          text_version="profile-v2", input_hash="p" * 64, vector=v(1.0)))

    prefs = {"locations": ["Singapore"], "target_roles": ["Backend Engineer"], "seniority": "Junior"}
    result = recommend_for_profile(db.session, str(db.version_a), prefs)
    assert [r.job_id for r in result.ranked] == [jobs.good, jobs.ok2]
    assert {b.job_id for b in result.blocked} == {jobs.recruiter, jobs.principal}
    seen = {r.job_id for r in result.ranked} | {b.job_id for b in result.blocked}
    for absent in ("closed", "london", "pending", "unembedded", "other_model"):
        assert getattr(jobs, absent) not in seen                          # ineligible / unusable / other model
    assert result.considered == 4

    no_checks = recommend_for_profile(db.session, str(db.version_a), prefs, apply_checks=False)
    assert [r.job_id for r in no_checks.ranked][:2] == [jobs.good, jobs.recruiter]
    excluded = recommend_for_profile(db.session, str(db.version_a), prefs, exclude_job_ids=[jobs.good])
    assert [r.job_id for r in excluded.ranked] == [jobs.ok2]
    assert len(recommend_for_profile(db.session, str(db.version_a), prefs, limit=1).ranked) == 1


def test_recommend_returns_none_without_a_usable_profile_vector(db):
    from job_hunter.embedding.db_retrieval import recommend_for_profile
    prefs = {"target_roles": ["Backend Engineer"]}
    assert recommend_for_profile(db.session, str(db.version_a), prefs) is None            # nothing stored yet
    DbProfileEmbeddingStore(db.session).save(str(db.version_a), EmbeddingRecord(
        status="pending", model=None, dimensions=None, text_version="profile-v2", input_hash="p" * 64, vector=None))
    assert recommend_for_profile(db.session, str(db.version_a), prefs) is None            # pending is not usable
    DbProfileEmbeddingStore(db.session).save(str(db.version_a), ready(version="profile-v2"))
    set_user(db.connection, db.user_b)
    assert recommend_for_profile(db.session, str(db.version_a), prefs) is None            # another user's vector is invisible


# ---- backfill and the for-you helpers ---------------------------------------------------------------
def test_backfill_embeds_open_jobs_and_confirmed_profiles_and_is_idempotent(db):
    from job_hunter.domain.models import Preference, Profile
    from job_hunter.embedding.backfill import NO_CONFIRMED_PROFILE, backfill_jobs, backfill_profiles

    closed = Job(title="Closed Engineer", description="x", status="closed")
    db.session.add(closed)
    db.session.flush()
    open_count = db.session.scalar(text("SELECT count(*) FROM jobs WHERE status='open'"))
    embedder = FakeEmbedder()
    first = backfill_jobs(db.session, embedder, batch_size=2)
    assert first["ready"] == open_count and sum(first.values()) == open_count
    assert db.session.scalar(text("SELECT count(*) FROM job_embeddings WHERE job_id=:j"), {"j": closed.id}) == 0
    again = backfill_jobs(db.session, embedder)
    assert again["unchanged"] == open_count and again["ready"] == 0

    set_user(db.connection, db.user_a)
    db.session.add(Profile(user_id=db.user_a, draft={}, revision=1, bank_revision=1, confirmed_revision=1))
    db.session.add(Preference(user_id=db.user_a, data={"roles": ["Backend Engineer"], "seniority": "Junior"}))
    version = db.session.get(ProfileVersion, db.version_a)
    version.data = {"headline": "Junior Backend Engineer", "summary": "Builds APIs.", "skills": ["Python"]}
    db.session.flush()
    profiles = backfill_profiles(db.session, embedder, [db.user_a, db.user_b])
    assert profiles["ready"] == 1 and profiles[NO_CONFIRMED_PROFILE] == 1
    set_user(db.connection, db.user_a)      # the backfill left the last user (B) set; read A's row as A
    row = db.session.execute(text("SELECT status, text_version FROM profile_embeddings WHERE profile_version_id=:v"),
                             {"v": db.version_a}).one()
    assert tuple(row) == ("ready", "profile-v2")
    assert backfill_profiles(db.session, embedder, [db.user_a])["unchanged"] == 1


def test_semantic_for_you_reports_why_it_cannot_be_used_and_pages_results(db):
    from job_hunter.embedding.for_you import NO_PROFILE, NO_VECTOR, page_items, semantic_for_you

    prefs = {"locations": ["Singapore"], "roles": ["Backend Engineer"]}
    assert semantic_for_you(db.session, None, prefs) == (None, NO_PROFILE)
    assert semantic_for_you(db.session, (str(db.version_a), 1, {}), prefs) == (None, NO_VECTOR)   # not embedded yet

    jobs = []
    for index in range(3):
        item = Job(title=f"Backend Engineer {index}", description="x", category="engineering", location="Singapore")
        db.session.add(item)
        jobs.append(item)
    db.session.flush()
    job_store, profile_store = DbJobEmbeddingStore(db.session), DbProfileEmbeddingStore(db.session)
    for index, item in enumerate(jobs):
        job_store.save(str(item.id), EmbeddingRecord(status="ready", model="m", dimensions=512, text_version=JOB_TEXT_VERSION,
                                                     input_hash="h" * 64, vector=v(1.0, 0.1 * index)))
    profile_store.save(str(db.version_a), EmbeddingRecord(status="ready", model="m", dimensions=512,
                                                          text_version="profile-v2", input_hash="p" * 64, vector=v(1.0)))
    result, reason = semantic_for_you(db.session, (str(db.version_a), 1, {}), prefs, exclude_job_ids=[str(jobs[2].id)])
    assert reason is None and [r.job_id for r in result.ranked] == [str(jobs[0].id), str(jobs[1].id)]
    out = lambda job: {"id": str(job.id), "title": job.title, "description": job.description, "skills": job.skills}
    items = page_items(db.session, result.ranked, offset=1, limit=5, job_out=out)
    assert [i["job"]["id"] for i in items] == [str(jobs[1].id)]
    assert items[0]["rank"] == 2 and items[0]["score"] is None and items[0]["reasons"]
    # typed search keeps the ranked order and reports a short, readable reason (never a caveat)
    from job_hunter.embedding.for_you import matching

    assert [r.job_id for r in matching(db.session, result.ranked, "engineer 1", out)] == [str(jobs[1].id)]
    assert [r.job_id for r in matching(db.session, result.ranked, "  ", out)] == [str(jobs[0].id), str(jobs[1].id)]
    assert matching(db.session, result.ranked, "no such text", out) == []
    skilled = page_items(db.session, result.ranked, 0, 5, out,
                         snapshot={"skills": ["Python"], "headline": "Backend Engineer"}, preferences={})
    assert all("not set" not in r and "not stated" not in r for item in skilled for r in item["reasons"])


# ---- save/confirm hook and the headline fallback -----------------------------------------------------
def _confirmed_profile(db, snapshot=None, roles=None):
    from job_hunter.domain.models import Preference, Profile

    set_user(db.connection, db.user_a)
    db.session.add(Profile(user_id=db.user_a, draft={}, revision=1, bank_revision=1, confirmed_revision=1))
    db.session.add(Preference(user_id=db.user_a, data={"roles": roles or [], "seniority": None}))
    db.session.get(ProfileVersion, db.version_a).data = snapshot or {
        "headline": "Junior Backend Engineer", "summary": "Builds APIs.", "skills": ["Python"]}
    db.session.flush()


class ExplodingEmbedder:
    def embed(self, texts):
        raise RuntimeError("boom: something nobody planned for")


def test_embed_after_save_is_off_by_default_and_best_effort_when_on(db, monkeypatch):
    from job_hunter.embedding.client import EmbedderUnavailable
    from job_hunter.embedding.profile_sync import NO_CONFIRMED_PROFILE, embed_after_save

    monkeypatch.delenv("EMBED_ON_SAVE", raising=False)
    assert embed_after_save(db.session, db.user_a, embedder=FakeEmbedder()) == "disabled"

    monkeypatch.setenv("EMBED_ON_SAVE", "1")
    set_user(db.connection, db.user_a)
    assert embed_after_save(db.session, db.user_a, embedder=FakeEmbedder()) == NO_CONFIRMED_PROFILE   # nothing confirmed yet

    _confirmed_profile(db)
    assert embed_after_save(db.session, db.user_a, embedder=FakeEmbedder()) == "ready"
    assert embed_after_save(db.session, db.user_a, embedder=FakeEmbedder()) == "unchanged"

    class Down:
        def embed(self, texts):
            raise EmbedderUnavailable("embedder is down")

    # roles change the embedded text; with the embedder down the save still goes through (status pending)
    pref = db.session.get(__import__("job_hunter.domain.models", fromlist=["Preference"]).Preference, db.user_a)
    pref.data = {"roles": ["Data Analyst"], "seniority": None}
    assert embed_after_save(db.session, db.user_a, embedder=Down()) == "pending"
    # an unexpected error is swallowed and the session stays usable
    pref.data = {"roles": ["Data Analyst", "Backend Engineer"], "seniority": None}
    assert embed_after_save(db.session, db.user_a, embedder=ExplodingEmbedder()) in {"error", "failed"}
    assert db.session.scalar(text("SELECT count(*) FROM jobs")) >= 1
    assert embed_after_save(db.session, db.user_a, embedder=FakeEmbedder()) == "ready"   # and it recovers


def test_role_check_falls_back_to_the_profile_headline_when_no_roles_are_set(db):
    from job_hunter.embedding.db_retrieval import recommend_for_profile

    _confirmed_profile(db)
    jobs = {}
    for name, title, category in (("eng", "Backend Engineer", "engineering"), ("rec", "Technical Recruiter", "people")):
        item = Job(title=title, description="x", category=category, location="Singapore")
        db.session.add(item)
        db.session.flush()
        jobs[name] = str(item.id)
    job_store, profile_store = DbJobEmbeddingStore(db.session), DbProfileEmbeddingStore(db.session)
    for key in jobs.values():
        job_store.save(key, EmbeddingRecord(status="ready", model="m", dimensions=512, text_version=JOB_TEXT_VERSION,
                                            input_hash="h" * 64, vector=v(1.0)))
    profile_store.save(str(db.version_a), EmbeddingRecord(status="ready", model="m", dimensions=512,
                                                          text_version="profile-v2", input_hash="p" * 64, vector=v(1.0)))
    result = recommend_for_profile(db.session, str(db.version_a), {"locations": ["Singapore"]})   # no target roles
    assert jobs["rec"] in {b.job_id for b in result.blocked}
    assert jobs["eng"] in {r.job_id for r in result.ranked}


def test_a_job_with_no_category_or_seniority_is_never_blocked(db):
    from job_hunter.embedding.db_retrieval import recommend_for_profile

    _confirmed_profile(db)
    blank = Job(title="Technical Recruiter", description="x", location="Singapore", category=None, seniority=None)
    odd = Job(title="Mystery Job", description="x", location="Singapore", category="astronaut", seniority=["bogus"])
    db.session.add_all([blank, odd])
    db.session.flush()
    job_store, profile_store = DbJobEmbeddingStore(db.session), DbProfileEmbeddingStore(db.session)
    for item in (blank, odd):
        job_store.save(str(item.id), EmbeddingRecord(status="ready", model="m", dimensions=512, text_version=JOB_TEXT_VERSION,
                                                     input_hash="h" * 64, vector=v(1.0)))
    profile_store.save(str(db.version_a), EmbeddingRecord(status="ready", model="m", dimensions=512,
                                                          text_version="profile-v2", input_hash="p" * 64, vector=v(1.0)))
    result = recommend_for_profile(db.session, str(db.version_a), {"locations": ["Singapore"], "target_roles": ["Backend Engineer"],
                                                                   "seniority": "Junior"})
    assert {str(blank.id), str(odd.id)} <= {r.job_id for r in result.ranked}      # unknown family / level: shown
    assert not result.blocked


def test_classification_report_counts_jobs_missing_a_category_or_seniority_per_source(db):
    from job_hunter.embedding.backfill import classification_report, unclassified_jobs

    db.session.add_all([
        Job(title="A", description="x", source="greenhouse", source_board="acme", category="engineering", seniority=["senior"]),
        Job(title="B", description="x", source="greenhouse", source_board="acme", category="other", seniority=[]),
        Job(title="C", description="x", source="greenhouse", source_board="acme", category=None, seniority=None),
        Job(title="D", description="x", source="lever", source_board="x", category="people", seniority=None, status="closed"),
    ])
    db.session.flush()
    report = classification_report(db.session)
    assert report["greenhouse/acme"] == {"jobs": 3, "category_missing": 1, "category_other": 1,
                                         "seniority_missing": 1, "seniority_unspecified": 1}
    assert "lever/x" not in report                                                   # closed jobs are not counted
    assert unclassified_jobs(report) >= 2


def test_text_report_summarises_heading_detection_per_source(db):
    from job_hunter.embedding.backfill import text_report

    good = ("About the team\nWe are a friendly team with a long history of building things together.\n"
            "What you'll do\n" + "Build and run reliable services for our customers every day. " * 3 +
            "\nRequirements\n" + "Strong Python and SQL experience in production settings. " * 3)
    db.session.add_all([Job(title="A", description=good, source="greenhouse", source_board="acme", location="Singapore"),
                        Job(title="B", description="Just a short blurb without any headings.", source="greenhouse",
                            source_board="acme", location="Singapore"),
                        Job(title="C", description=None, source="lever", source_board="x", location="Singapore")])
    db.session.flush()
    report = text_report(db.session)
    acme = report["greenhouse/acme"]
    assert acme["jobs"] == 2 and acme["v1_uses_sections"] == 1 and acme["v3_uses_sections"] == 1
    assert acme["fallback_reasons"] == {"no recognisable heading": 1} and 0 < acme["avg_kept_share_v1"] < 1
    assert report["lever/x"]["fallback_reasons"] == {"no description": 1}


def test_the_vector_cache_gives_the_same_for_you_results_and_sees_new_vectors(db, monkeypatch):
    import random
    from job_hunter.embedding import vector_pool
    from job_hunter.embedding.db_retrieval import recommend_for_profile

    rng = random.Random(7)
    titles = ["Backend Engineer", "Platform Engineer", "Data Engineer", "Software Engineer", "Technical Recruiter",
              "Senior Backend Engineer", "Frontend Developer", "Data Analyst", "DevOps Engineer", "Product Manager"]
    job_store = DbJobEmbeddingStore(db.session)
    ids = []
    for index in range(40):
        title = titles[index % len(titles)]
        item = Job(title=title, description="x", category="engineering" if "Engineer" in title or "Developer" in title else "data",
                   seniority=classify_seniority(title)[0], location="Singapore", status="closed" if index % 9 == 0 else "open")
        db.session.add(item)
        db.session.flush()
        ids.append(str(item.id))
        job_store.save(str(item.id), EmbeddingRecord(status="ready", model="m", dimensions=512, text_version=JOB_TEXT_VERSION,
                                                     input_hash="h" * 64, vector=tuple(rng.uniform(-1, 1) for _ in range(512))))
    DbProfileEmbeddingStore(db.session).save(str(db.version_a), EmbeddingRecord(
        status="ready", model="m", dimensions=512, text_version="profile-v2", input_hash="p" * 64,
        vector=tuple(rng.uniform(-1, 1) for _ in range(512))))

    def run(**kwargs):
        result = recommend_for_profile(db.session, str(db.version_a), {"target_roles": ["Backend Engineer"]}, limit=None, **kwargs)
        return ([(r.job_id, round(r.similarity, 9), r.role, r.seniority) for r in result.ranked],
                [(b.job_id, round(b.similarity, 9)) for b in result.blocked], result.considered)

    vector_pool.clear()
    for kwargs in ({}, {"include_closed": True}, {"exclude_job_ids": ids[:5]}):
        monkeypatch.setenv("JOB_POOL_CACHE", "1")
        cached = run(**kwargs)
        monkeypatch.setenv("JOB_POOL_CACHE", "0")
        assert run(**kwargs) == cached and cached[2] > 0

    monkeypatch.setenv("JOB_POOL_CACHE", "1")
    before = run()[2]
    extra = Job(title="Backend Engineer", description="x", category="engineering", seniority=[], location="Singapore", status="open")
    db.session.add(extra)
    db.session.flush()
    job_store.save(str(extra.id), EmbeddingRecord(status="ready", model="m", dimensions=512, text_version=JOB_TEXT_VERSION,
                                                  input_hash="h" * 64, vector=tuple(rng.uniform(-1, 1) for _ in range(512))))
    assert run()[2] == before + 1                                  # a new vector is seen on the next request
