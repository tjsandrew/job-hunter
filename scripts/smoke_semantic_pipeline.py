"""Local, rollback-only smoke test of job import, classification, embedding and ranking."""

from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from job_hunter.config import settings
from job_hunter.domain.models import Base, Job, ProfileVersion, User
from job_hunter.embedding import HttpEmbedder, ProfileEmbedRequest, embed_profile
from job_hunter.embedding.backfill import backfill_jobs, classification_report
from job_hunter.embedding.db_retrieval import recommend_for_profile
from job_hunter.embedding.db_store import DbProfileEmbeddingStore
from job_hunter.import_jobs import SQLAlchemyJobRepository, reclassify_jobs, upsert_records
from job_hunter.recommendations import rank_jobs


def run_migration(connection, filename):
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    migrations = root / "backend" / "migrations" if (root / "backend").is_dir() else root / "migrations"
    path = migrations / "versions" / filename
    spec = spec_from_file_location(filename.removesuffix(".py"), path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()


def main():
    engine = create_engine(settings.migration_database_url or settings.database_url)
    schema = "smoke_" + uuid4().hex
    titles = (
        ("Backend Engineer", None),
        ("Technical Recruiter, Backend Engineering", None),
        ("Principal Backend Engineer", None),
        ("Senior Backend Engineer", "Junior"),
    )
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
                Base.metadata.create_all(connection, checkfirst=False)
                run_migration(connection, "0012_embedding_tables.py")
                session = Session(bind=connection)
                legacy = Job(title="Legacy Engineer", description="x", status="closed")
                session.add(legacy)
                session.flush()
                connection.execute(text("""INSERT INTO job_match_features (job_id, feature_version, features)
                    VALUES (:job_id, 'features-v2', CAST(:features AS jsonb))"""),
                    {"job_id": legacy.id, "features": '{"seniority_levels":["junior"],"seniority_source":"stated"}'})
                run_migration(connection, "0013_job_seniority.py")
                session.refresh(legacy)
                assert legacy.seniority == ["junior"] and legacy.seniority_source == "stated"
                assert connection.execute(text("SELECT to_regclass('job_match_features')")).scalar_one() is None
                records = [
                    {"source": "synthetic", "source_board": "smoke", "external_id": str(index),
                     "dedup_key": f"synthetic:smoke:{index}", "source_url": "https://example.invalid/jobs",
                     "title": title, "employer": "Smoke Test", "location": "Singapore",
                     "description": "Build and maintain backend APIs with Python for the payments platform.",
                     "stated_seniority": stated}
                    for index, (title, stated) in enumerate(titles)
                ]
                stats = upsert_records(SQLAlchemyJobRepository(session), records)
                assert (stats.new, stats.errors) == (4, 0), stats
                session.flush()
                jobs = {job.title: job for job in session.scalars(select(Job))}
                assert jobs[titles[1][0]].category == "people"
                assert jobs[titles[2][0]].seniority == ["lead"]
                assert jobs[titles[3][0]].seniority == ["junior"]
                assert jobs[titles[3][0]].seniority_source == "stated"
                classified = reclassify_jobs(session.scalars(select(Job)))
                assert classified["updated"] == 1 and classified["kept_stated_seniority"] == 2
                assert reclassify_jobs(session.scalars(select(Job)))["updated"] == 0
                report = classification_report(session)
                assert report["synthetic/smoke"]["category_missing"] == 0
                assert report["synthetic/smoke"]["seniority_missing"] == 0

                user = User(auth_subject="smoke-" + uuid4().hex, display_name="Smoke")
                session.add(user)
                session.flush()
                version = ProfileVersion(user_id=user.id, revision=1,
                                         data={"headline": "Junior Backend Engineer", "summary": "Builds Python APIs.",
                                               "skills": ["Python"]}, content_hash="smoke")
                session.add(version)
                session.flush()
                embedder = HttpEmbedder("http://embedder:8100", timeout_seconds=60)
                first = backfill_jobs(session, embedder, batch_size=4)
                assert first["ready"] == 4, first
                second = backfill_jobs(session, embedder, batch_size=4)
                assert second["unchanged"] == 4, second
                outcome = embed_profile(ProfileEmbedRequest(profile_version_id=str(version.id),
                    snapshot=version.data, target_roles=["Backend Engineer"]),
                    embedder=embedder, store=DbProfileEmbeddingStore(session))
                assert outcome.status == "ready", outcome
                result = recommend_for_profile(session, str(version.id),
                    {"target_roles": ["Backend Engineer"], "seniority": "Junior", "locations": ["Singapore"]})
                assert result is not None
                ranked = {row.job_id for row in result.ranked}
                blocked = {row.job_id for row in result.blocked}
                assert str(jobs[titles[0][0]].id) in ranked
                assert str(jobs[titles[3][0]].id) in ranked
                assert str(jobs[titles[1][0]].id) in blocked
                assert str(jobs[titles[2][0]].id) in blocked
                baseline = rank_jobs(
                    [{"id": str(job.id), "title": job.title, "description": job.description,
                      "category": job.category, "location": job.location, "status": job.status,
                      "skills": job.skills} for job in jobs.values()],
                    version.data, {"target_roles": ["Backend Engineer"], "locations": ["Singapore"]})
                assert len(baseline) == 4 and all("score" in row for row in baseline)
                print(f"PASS: imported=4, embedded=4, unchanged=4, semantic={len(ranked)}, "
                      f"blocked={len(blocked)}, lexical={len(baseline)}")
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
