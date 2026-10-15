"""Data migrations and seed must work as a non-owner with forced tenant RLS."""
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from job_hunter.config import settings
from job_hunter.demo import LEGACY_PROFILE
from job_hunter.domain.identity import DEV_USERS
from job_hunter.domain.models import Base, Profile, ProfileItem, User
from job_hunter.seed import seed_session

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_INTEGRATION") != "1",
                               reason="set RUN_DB_INTEGRATION=1 against local PostgreSQL")


@pytest.fixture
def restricted_connection():
    """DDL setup rolls back entirely; tested data writes run under an empty role."""
    engine = create_engine(settings.migration_database_url or settings.database_url)
    suffix = uuid4().hex
    schema, role = "bank_rls_" + suffix, "bank_writer_" + suffix
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE ROLE "{role}" NOSUPERUSER NOBYPASSRLS'))
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            Base.metadata.create_all(connection, checkfirst=False)
            for table, owner_column in {"users": "id", "profiles": "user_id", "preferences": "user_id",
                                       "profile_items": "user_id", "profile_imports": "user_id",
                                       "profile_versions": "user_id", "user_settings": "user_id"}.items():
                connection.execute(text(f'ALTER TABLE "{schema}".{table} ENABLE ROW LEVEL SECURITY'))
                connection.execute(text(f'ALTER TABLE "{schema}".{table} FORCE ROW LEVEL SECURITY'))
                connection.execute(text(f"""CREATE POLICY tenant_isolation ON "{schema}".{table}
                    USING ({owner_column}=NULLIF(current_setting('app.user_id', true),'')::uuid)
                    WITH CHECK ({owner_column}=NULLIF(current_setting('app.user_id', true),'')::uuid)"""))
            connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
            connection.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))
            connection.execute(text(f'SET LOCAL ROLE "{role}"'))
            flags = connection.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
            assert flags == (False, False)
            assert connection.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname=:schema AND tableowner=current_user"),
                                      {"schema": schema}).scalar_one() == 0
            yield connection
        finally:
            transaction.rollback()
    engine.dispose()


def context(connection, owner):
    connection.execute(text("SELECT set_config('app.user_id', :owner, true)"), {"owner": str(owner)})


def test_profile_data_migration_runs_as_non_owner_under_forced_rls(restricted_connection):
    connection = restricted_connection
    for key, (owner, name) in DEV_USERS.items():
        context(connection, owner)
        with Session(bind=connection) as db:
            db.add(User(id=owner, auth_subject=key, display_name=name))
            db.flush()
            db.add(Profile(user_id=owner, draft=LEGACY_PROFILE if key == "alice" else {},
                           revision=7, bank_revision=1, confirmed_revision=6 if key == "alice" else None))
            db.flush()
    connection.execute(text("SELECT set_config('app.user_id', '', true)"))
    assert connection.execute(select(Profile.user_id)).all() == []
    path = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0010_profile_bank.py"
    spec = importlib.util.spec_from_file_location("profile_bank_rls_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.migrate_profile_data(connection, [owner for owner, _ in DEV_USERS.values()])
    alice, _ = DEV_USERS["alice"]
    casey, _ = DEV_USERS["casey"]
    context(connection, alice)
    with Session(bind=connection) as db:
        profile = db.get(Profile, alice)
        assert profile.bank_revision == 7 and profile.confirmed_revision == 6
        assert "skills" not in profile.draft
        items = db.scalars(select(ProfileItem)).all()
        assert len(items) == sum(len(LEGACY_PROFILE[field]) for field in ("skills", "experience", "education", "projects"))
        assert all(item.user_id == alice for item in items)
    context(connection, casey)
    assert connection.execute(select(ProfileItem.id)).all() == []
    assert connection.execute(select(Profile.bank_revision)).scalar_one() == 7


def test_seed_runs_as_non_owner_and_flushes_before_switching_tenants(restricted_connection):
    connection = restricted_connection
    with Session(bind=connection) as db:
        seed_session(db)
        db.flush()
        # Seed is idempotent, including when nothing is bypassing forced RLS.
        seed_session(db)
        db.flush()
        alice, _ = DEV_USERS["alice"]
        casey, _ = DEV_USERS["casey"]
        context(connection, alice)
        assert db.get(User, alice) is not None
        assert db.get(Profile, alice).draft["name"] == LEGACY_PROFILE["name"]
        assert db.scalars(select(ProfileItem)).all()
        context(connection, casey)
        assert db.get(User, casey) is not None
        assert db.get(Profile, casey) is not None
        assert db.scalars(select(ProfileItem)).all() == []
