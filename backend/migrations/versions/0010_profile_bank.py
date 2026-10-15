"""Split profile facts into a tenant-owned bank without losing downgrade data."""
from datetime import datetime
import json
from uuid import UUID

from alembic import op
import sqlalchemy as sa

from job_hunter.profile_bank.migration import migrate_legacy_profile, restore_legacy_profile

revision = "0010_profile_bank"
down_revision = "0009_application_packets"
branch_labels = None
depends_on = None

# Older clients ignore this key. It carries richer bank data across a downgrade,
# including wording IDs, unsupported legacy kinds, and archived entries.
ROUNDTRIP_KEY = "_profile_bank_v1"


def _constraint(table, name, definition):
    op.execute(f"""DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='{table}'::regclass
                     AND conname='{name}') THEN
        ALTER TABLE {table} ADD CONSTRAINT {name} {definition};
      END IF;
    END $$""")


def _table(name, connection=None):
    return sa.Table(name, sa.MetaData(), autoload_with=connection if connection is not None else op.get_bind())


def _json_row(row):
    return json.loads(json.dumps(dict(row), default=lambda v: v.tolist() if hasattr(v, "tolist") else str(v)))


def _restore_rows(connection, table_name, rows):
    table = _table(table_name, connection)
    for raw in rows:
        row = dict(raw)
        for column in table.columns:
            if row.get(column.name) is not None:
                if isinstance(column.type, sa.DateTime):
                    row[column.name] = datetime.fromisoformat(row[column.name])
                elif isinstance(column.type, sa.UUID):
                    row[column.name] = UUID(row[column.name])
        connection.execute(table.insert(), row)


def _owner_ids():
    # FORCE RLS also covers users. The DDL migrator temporarily gains only the
    # tenant-ID discovery read; application roles keep their normal policies.
    op.execute("CREATE POLICY profile_bank_migration_owners ON users FOR SELECT TO CURRENT_USER USING (true)")
    try:
        return op.get_bind().execute(sa.text("SELECT id FROM users")).scalars().all()
    finally:
        op.execute("DROP POLICY profile_bank_migration_owners ON users")


def upgrade():
    op.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS bank_revision integer NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS profile_epoch integer NOT NULL DEFAULT 0")
    _constraint("uploads", "uq_upload_id_user", "UNIQUE(id, user_id)")
    _constraint("documents", "uq_document_id_user", "UNIQUE(id, user_id)")
    op.execute("""CREATE TABLE IF NOT EXISTS profile_items (
      id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id),
      kind text NOT NULL CONSTRAINT ck_profile_item_kind CHECK (kind IN
        ('experience','education','project','skill','certification','award','volunteering','custom')),
      position integer NOT NULL DEFAULT 0, data jsonb NOT NULL,
      tags text[] NOT NULL DEFAULT '{}',
      origin text NOT NULL DEFAULT 'manual' CONSTRAINT ck_profile_item_origin CHECK (origin IN ('manual','import')),
      import_id uuid, parent_id uuid, revision integer NOT NULL DEFAULT 1,
      archived_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_profile_item_id_user UNIQUE(id, user_id),
      CONSTRAINT fk_profile_item_parent_owner FOREIGN KEY(parent_id, user_id)
        REFERENCES profile_items(id, user_id))""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_profile_items_user_kind ON profile_items(user_id,kind,position)")
    op.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_profile_skill_name
      ON profile_items(user_id, lower(data->>'name')) WHERE kind='skill' AND archived_at IS NULL""")
    op.execute("""CREATE TABLE IF NOT EXISTS profile_imports (
      id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id),
      source_type text NOT NULL CONSTRAINT ck_profile_import_source CHECK (source_type IN ('upload','document','json_resume','text')),
      upload_id uuid, document_id uuid, input_ref jsonb NOT NULL, input_payload jsonb, task_id uuid,
      profile_epoch integer NOT NULL DEFAULT 0,
      status text NOT NULL DEFAULT 'pending' CONSTRAINT ck_profile_import_status CHECK (status IN ('pending','ready','failed','applied','discarded')),
      parser text, candidates jsonb NOT NULL DEFAULT '[]', error_code text,
      created_at timestamptz NOT NULL DEFAULT now(), applied_at timestamptz,
      CONSTRAINT uq_profile_import_id_user UNIQUE(id,user_id),
      CONSTRAINT fk_profile_import_upload_owner FOREIGN KEY(upload_id,user_id) REFERENCES uploads(id,user_id),
      CONSTRAINT fk_profile_import_document_owner FOREIGN KEY(document_id,user_id) REFERENCES documents(id,user_id))""")
    op.execute("""CREATE TABLE IF NOT EXISTS user_settings (
      user_id uuid PRIMARY KEY REFERENCES users(id), id uuid NOT NULL,
      resume_defaults jsonb NOT NULL DEFAULT '{}', revision integer NOT NULL DEFAULT 1,
      CONSTRAINT uq_user_settings_id_user UNIQUE(id,user_id))""")
    for name, kind in {"embedding": "vector(512)", "embedding_model": "text", "embedding_dims": "integer",
                       "embedding_text_version": "text", "embedding_status": "text"}.items():
        op.execute(f"ALTER TABLE profile_versions ADD COLUMN IF NOT EXISTS {name} {kind}")
    for table in ("profile_items", "profile_imports", "user_settings"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"""CREATE POLICY tenant_isolation ON {table}
          USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
          WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)""")
    migrate_profile_data(op.get_bind(), _owner_ids())


def migrate_profile_data(connection, owner_ids):
    """Run the data transform under each tenant, including reads under forced RLS."""
    profiles = _table("profiles", connection)
    items = _table("profile_items", connection)
    for owner in owner_ids:
        connection.execute(sa.text("SELECT set_config('app.user_id', :owner, true)"), {"owner": str(owner)})
        profile = connection.execute(sa.select(profiles).where(profiles.c.user_id == owner)).mappings().one_or_none()
        if profile is None:
            continue
        draft = dict(profile["draft"])
        saved = draft.pop(ROUNDTRIP_KEY, None)
        if saved:
            basics = saved["basics"]
            # Insert parents first while retaining the same owner constraint.
            pending = list(saved["profile_items"])
            inserted = set()
            while pending:
                ready = [row for row in pending if not row.get("parent_id") or row["parent_id"] in inserted]
                if not ready:
                    raise ValueError("Cannot restore cyclic profile item parents")
                _restore_rows(connection, "profile_items", ready)
                inserted.update(row["id"] for row in ready)
                pending = [row for row in pending if row not in ready]
            _restore_rows(connection, "profile_imports", saved["profile_imports"])
            _restore_rows(connection, "user_settings", saved["user_settings"])
            versions = _table("profile_versions", connection)
            for version in saved.get("version_embeddings", []):
                values = {k: v for k, v in version.items() if k != "id"}
                connection.execute(versions.update().where(versions.c.id == UUID(version["id"])).values(**values))
            bank_revision = saved["bank_revision"]
            epoch = saved["profile_epoch"]
        else:
            basics, migrated = migrate_legacy_profile(draft, profile["user_id"])
            for item in migrated:
                connection.execute(items.insert().values(**item, user_id=profile["user_id"], created_at=profile["updated_at"], updated_at=profile["updated_at"]))
            bank_revision, epoch = profile["revision"], profile["profile_epoch"]
        connection.execute(profiles.update().where(profiles.c.user_id == profile["user_id"])
                              .values(draft=basics, bank_revision=bank_revision, profile_epoch=epoch))


def downgrade():
    profiles = _table("profiles")
    tables = {name: _table(name) for name in ("profile_items", "profile_imports", "user_settings")}
    versions = _table("profile_versions")
    for owner in _owner_ids():
        op.get_bind().execute(sa.text("SELECT set_config('app.user_id', :owner, true)"), {"owner": str(owner)})
        profile = op.get_bind().execute(sa.select(profiles).where(profiles.c.user_id == owner)).mappings().one_or_none()
        if profile is None:
            continue
        saved = {name: [_json_row(row) for row in op.get_bind().execute(sa.select(table).where(table.c.user_id == owner)).mappings()]
                 for name, table in tables.items()}
        saved.update(basics=profile["draft"], bank_revision=profile["bank_revision"], profile_epoch=profile["profile_epoch"])
        saved["version_embeddings"] = [_json_row(row) for row in op.get_bind().execute(sa.select(
            versions.c.id, versions.c.embedding, versions.c.embedding_model, versions.c.embedding_dims,
            versions.c.embedding_text_version, versions.c.embedding_status).where(versions.c.user_id == owner)).mappings()]
        draft = restore_legacy_profile(profile["draft"], saved["profile_items"])
        draft[ROUNDTRIP_KEY] = saved
        op.get_bind().execute(profiles.update().where(profiles.c.user_id == owner).values(draft=draft))
    for table in ("profile_imports", "profile_items", "user_settings"):
        op.drop_table(table)
    for name in ("embedding_status", "embedding_text_version", "embedding_dims", "embedding_model", "embedding"):
        op.execute(f"ALTER TABLE profile_versions DROP COLUMN IF EXISTS {name}")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS uq_document_id_user")
    op.execute("ALTER TABLE uploads DROP CONSTRAINT IF EXISTS uq_upload_id_user")
    op.execute("ALTER TABLE profiles DROP COLUMN IF EXISTS profile_epoch")
    op.execute("ALTER TABLE profiles DROP COLUMN IF EXISTS bank_revision")
