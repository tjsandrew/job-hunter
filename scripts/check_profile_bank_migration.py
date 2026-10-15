"""Verify profile-bank migrations in a disposable PostgreSQL database.

Run with MIGRATION_DATABASE_URL and the backend dependencies configured, e.g.:
  docker compose run --rm --no-deps -v "$PWD/scripts:/app/scripts:ro" \
    api python /app/scripts/check_profile_bank_migration.py

The configured database is never migrated or modified. Only a randomly named
check database created by this process is dropped, including after failures.
"""
import json
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from job_hunter.config import settings
from job_hunter.demo import LEGACY_PROFILE
from job_hunter.profile_bank.snapshots import assemble_profile_snapshot

OLD_REVISION = "0009_application_packets"
BANK_REVISION = "0010_profile_bank"
TABLES = ("profiles", "profile_items", "profile_imports", "user_settings", "profile_versions")
PRE_BANK_COLUMNS = json.loads((Path(__file__).with_name("schema_0009_columns.json")).read_text())
EMBEDDING_COLUMNS = ("embedding", "embedding_model", "embedding_dims", "embedding_text_version", "embedding_status")


def alembic_config():
    for location in (Path.cwd() / "alembic.ini", Path(__file__).resolve().parents[1] / "backend" / "alembic.ini"):
        if location.is_file():
            config = Config(str(location))
            config.set_main_option("script_location", str(location.parent / "migrations"))
            return config
    raise RuntimeError("Run from the backend directory or the repository checkout")


def seed_old_schema(engine):
    """0001 uses live ORM metadata; remove future additions to emulate true 0009."""
    owner, version_id = uuid4(), uuid4()
    with engine.begin() as connection:
        for table in ("profile_imports", "profile_items", "user_settings"):
            connection.execute(text(f"DROP TABLE {table}"))
        for column in ("bank_revision", "profile_epoch"):
            connection.execute(text(f"ALTER TABLE profiles DROP COLUMN {column}"))
        for column in EMBEDDING_COLUMNS:
            connection.execute(text(f"ALTER TABLE profile_versions DROP COLUMN {column}"))
        for table, constraint in (("uploads", "uq_upload_id_user"), ("documents", "uq_document_id_user")):
            connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}"))
        # Drop any other column the live ORM added after 0009, so later migrations must create it.
        for table, columns in PRE_BANK_COLUMNS.items():
            live = connection.execute(text("""SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table"""), {"table": table}).scalars().all()
            for column in sorted(set(live) - set(columns)):
                connection.execute(text(f'ALTER TABLE {table} DROP COLUMN "{column}"'))
        connection.execute(text("""INSERT INTO users(id, auth_subject, display_name, plan, created_at)
            VALUES(:id, 'migration-check', 'Fictional Migration Check', 'free', now())"""), {"id": owner})
        connection.execute(text("""INSERT INTO profiles(user_id, draft, revision, confirmed_revision, updated_at)
            VALUES(:owner, CAST(:draft AS json), 7, 6, now())"""),
            {"owner": owner, "draft": json.dumps(LEGACY_PROFILE)})
        connection.execute(text("""INSERT INTO profile_versions(id, user_id, revision, data, content_hash, created_at)
            VALUES(:id, :owner, 6, CAST(:draft AS json), :hash, now())"""),
            {"id": version_id, "owner": owner, "draft": json.dumps(LEGACY_PROFILE), "hash": "0" * 64})
    return owner, version_id


def verify_legacy_upgrade(engine):
    with engine.connect() as connection:
        profile = connection.execute(text("SELECT * FROM profiles")).mappings().one()
        items = [dict(row) for row in connection.execute(text("SELECT * FROM profile_items")).mappings()]
        snapshot = assemble_profile_snapshot(profile["draft"], items, profile["bank_revision"])
        snapshot.pop("bank_revision")
        snapshot.pop("bullets")
        assert snapshot == LEGACY_PROFILE, "Migration changed the legacy snapshot contract"
        assert profile["bank_revision"] == profile["revision"] == 7
        assert profile["confirmed_revision"] == 6
        version = connection.execute(text("SELECT revision, data FROM profile_versions")).mappings().one()
        assert version["revision"] == 6 and version["data"] == LEGACY_PROFILE
        assert not any(key in profile["draft"] for key in ("skills", "experience", "education", "projects"))
        assert all(point.get("id") for item in items for point in item["data"].get("bullets", []))


def add_rich_bank(engine, owner, version_id):
    with engine.begin() as connection:
        parent = connection.execute(text("SELECT id FROM profile_items WHERE kind='experience' ORDER BY position LIMIT 1")).scalar_one()
        rich = {"title": "Community interests", "bullets": [
            {"id": "b_roundtrip", "text": "Organised fictional practice sessions.", "tags": ["leadership"],
             "provenance": {"origin": "user"},
             "alternatives": [{"id": "v_roundtrip", "text": "Led synthetic-data practice sessions."}]}]}
        connection.execute(text("""INSERT INTO profile_items(id, user_id, kind, data, tags, revision, archived_at)
            VALUES(:id, :owner, 'custom', CAST(:data AS jsonb), ARRAY['leadership'], 3, now())"""),
            {"id": uuid4(), "owner": owner, "data": json.dumps(rich)})
        connection.execute(text("""INSERT INTO profile_items(id, user_id, kind, parent_id, data)
            VALUES(:id, :owner, 'project', :parent, CAST(:data AS jsonb))"""),
            {"id": uuid4(), "owner": owner, "parent": parent,
             "data": json.dumps({"name": "Nested fictional project", "bullets": []})})
        connection.execute(text("""INSERT INTO user_settings(id, user_id, resume_defaults, revision)
            VALUES(:id, :owner, CAST(:data AS jsonb), 4)"""),
            {"id": uuid4(), "owner": owner, "data": json.dumps({"template": "classic"})})
        connection.execute(text("""INSERT INTO profile_imports(id, user_id, source_type, input_ref, input_payload, status, profile_epoch)
            VALUES(:id, :owner, 'text', '{}', CAST(:data AS jsonb), 'ready', 2)"""),
            {"id": uuid4(), "owner": owner, "data": json.dumps("Fictional immutable input text")})
        connection.execute(text("""UPDATE profile_versions SET embedding=CAST(:vector AS vector),
            embedding_model='migration-check', embedding_dims=512,
            embedding_text_version='profile-v1', embedding_status='ready' WHERE id=:id"""),
            {"id": version_id, "vector": str([0.25] * 512)})
        connection.execute(text("UPDATE profiles SET bank_revision=12, profile_epoch=2"))


def dump(engine):
    with engine.connect() as connection:
        return {table: connection.execute(text(
            f"SELECT row_to_json(t) FROM (SELECT * FROM {table} ORDER BY 1) t")).scalars().all()
            for table in TABLES}


def verify_rls(engine):
    with engine.connect() as connection:
        tables = connection.execute(text("""SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class WHERE relname IN ('profile_items','profile_imports','user_settings')""")).all()
        assert len(tables) == 3 and all(enabled and forced for _, enabled, forced in tables)
        policies = connection.execute(text("""SELECT tablename, qual, with_check FROM pg_policies
            WHERE tablename IN ('profile_items','profile_imports','user_settings')
            AND policyname='tenant_isolation'""")).all()
        assert len(policies) == 3
        assert all("app.user_id" in using and "app.user_id" in check for _, using, check in policies)
        dims = connection.execute(text("SELECT vector_dims(embedding) FROM profile_versions")).scalar_one()
        assert dims == 512


def verify_orm_matches_schema(engine):
    """Every ORM column must exist after migrating a true pre-bank database to head."""
    from job_hunter.domain.models import Base
    with engine.connect() as connection:
        missing = []
        for table in Base.metadata.sorted_tables:
            live = set(connection.execute(text("""SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table"""), {"table": table.name}).scalars())
            missing += [f"{table.name}.{column.name}" for column in table.columns if column.name not in live]
    assert not missing, f"ORM columns with no migration: {', '.join(missing)}"


def main():
    if not settings.migration_database_url:
        raise RuntimeError("MIGRATION_DATABASE_URL must be explicitly configured")
    source_url = make_url(settings.migration_database_url)
    database_name = "profile_bank_check_" + uuid4().hex
    test_url = source_url.set(database=database_name)
    admin = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    engine = None
    created = False
    previous_url = os.environ.get("MIGRATION_DATABASE_URL")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        created = True
        # Alembic env.py reads this setting; preserve it for callers after checks.
        os.environ["MIGRATION_DATABASE_URL"] = test_url.render_as_string(hide_password=False)
        config = alembic_config()
        command.upgrade(config, OLD_REVISION)
        engine = create_engine(test_url)
        owner, version_id = seed_old_schema(engine)
        command.upgrade(config, BANK_REVISION)
        verify_legacy_upgrade(engine)
        add_rich_bank(engine, owner, version_id)
        before = dump(engine)
        command.downgrade(config, OLD_REVISION)
        with engine.connect() as connection:
            draft = connection.execute(text("SELECT draft FROM profiles")).scalar_one()
            marker = draft["_profile_bank_v1"]
            assert marker["basics"] == before["profiles"][0]["draft"]
            assert marker["bank_revision"] == 12 and marker["profile_epoch"] == 2
            assert len(marker["profile_items"]) == len(before["profile_items"])
            assert draft["skills"] == LEGACY_PROFILE["skills"]
        command.upgrade(config, BANK_REVISION)
        assert dump(engine) == before, "Downgrade/upgrade changed stored data"
        verify_rls(engine)
        command.upgrade(config, "head")
        verify_orm_matches_schema(engine)
        print("PASS: legacy 0009 upgrade, rich bank roundtrip, stable IDs, vector(512), forced tenant RLS, "
              "and every ORM column created by migrations")
    finally:
        if previous_url is None:
            os.environ.pop("MIGRATION_DATABASE_URL", None)
        else:
            os.environ["MIGRATION_DATABASE_URL"] = previous_url
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
        admin.dispose()


if __name__ == "__main__":
    main()
