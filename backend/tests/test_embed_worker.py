"""Embed worker pieces that need no database: the S3 flag, the save-time switch, the Lambda handler, the
in-process embedder and the role statements. (The database behaviour is in integration/test_embed_worker_db.py.)"""
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from job_hunter import embed_worker
from job_hunter.adapters import database
from job_hunter.embedding import db_role, flag, profile_sync
from job_hunter.embedding.settings import embed_mode, embed_on_save_enabled, embedder_model_name
from job_hunter.embedding.worker import PassResult


# ---- EMBED_ON_SAVE switch -------------------------------------------------------------------------------

@pytest.mark.parametrize("value,mode", [("queue", "queue"), (" QUEUE ", "queue"), ("1", "sync"), ("true", "sync"),
                                        ("on", "sync"), ("0", "off"), ("", "off"), ("nonsense", "off")])
def test_embed_mode(monkeypatch, value, mode):
    monkeypatch.setenv("EMBED_ON_SAVE", value)
    assert embed_mode() == mode
    assert embed_on_save_enabled() is (mode == "sync")   # the old switch only means "embed in the request"


def test_embed_mode_unset(monkeypatch):
    monkeypatch.delenv("EMBED_ON_SAVE", raising=False)
    assert embed_mode() == "off"


def test_queue_mode_marks_the_session_and_does_not_embed(monkeypatch):
    monkeypatch.setenv("EMBED_ON_SAVE", "queue")
    session = SimpleNamespace(info={})
    embedder = Mock()
    assert profile_sync.embed_after_save(session, "user", embedder=embedder) == "queued"
    assert session.info[flag.SESSION_KEY] is True
    embedder.embed.assert_not_called()


def test_off_mode_does_nothing(monkeypatch):
    monkeypatch.setenv("EMBED_ON_SAVE", "0")
    session = SimpleNamespace(info={})
    assert profile_sync.embed_after_save(session, "user") == "disabled"
    assert session.info == {}


# ---- the S3 flag ----------------------------------------------------------------------------------------

def test_flag_is_an_empty_object_under_the_prefix_and_keys_are_unique():
    client = MagicMock()
    assert flag.write_flag(client=client, bucket="documents") is True
    assert flag.write_flag(client=client, bucket="documents") is True
    first, second = [call.kwargs for call in client.put_object.call_args_list]
    assert first["Bucket"] == "documents" and first["Body"] == b""
    assert first["Key"].startswith(flag.FLAG_PREFIX) and second["Key"].startswith(flag.FLAG_PREFIX)
    assert first["Key"] != second["Key"]


def test_flag_failures_never_raise():
    client = MagicMock()
    client.put_object.side_effect = RuntimeError("endpoint unreachable")
    assert flag.write_flag(client=client, bucket="documents") is False
    assert flag.write_flag(client=MagicMock(), bucket="") is False   # no bucket configured


def test_send_requested_writes_once_and_only_when_marked():
    client = MagicMock()
    session = SimpleNamespace(info={})
    assert flag.send_requested(session, client=client, bucket="documents") is False
    client.put_object.assert_not_called()
    flag.request_embedding(session)
    assert flag.send_requested(session, client=client, bucket="documents") is True
    assert flag.send_requested(session, client=client, bucket="documents") is False   # the mark is consumed
    assert client.put_object.call_count == 1


def test_get_db_writes_the_flag_only_after_the_commit(monkeypatch):
    events = []

    class FakeSession:
        def __init__(self):
            self.info = {}

        def begin(self):
            events.append("begin")

        def execute(self, *args, **kwargs):
            pass

        def get(self, model, key):
            return SimpleNamespace(id=key)

        def commit(self):
            events.append("commit")

        def rollback(self):
            events.append("rollback")

        def close(self):
            events.append("close")

    monkeypatch.setattr(database, "SessionLocal", FakeSession)
    monkeypatch.setattr(database.embed_flag, "send_requested", lambda session: events.append("flag"))
    generator = database.get_db("alice")
    session = next(generator)
    flag.request_embedding(session)
    with pytest.raises(StopIteration):
        next(generator)
    assert events.index("commit") < events.index("flag")


def test_get_db_does_not_write_the_flag_when_the_request_fails(monkeypatch):
    sent = []

    class FakeSession:
        info = {}

        def begin(self): pass
        def execute(self, *args, **kwargs): pass
        def get(self, model, key): return SimpleNamespace(id=key)
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass

    monkeypatch.setattr(database, "SessionLocal", FakeSession)
    monkeypatch.setattr(database.embed_flag, "send_requested", lambda session: sent.append(True))
    generator = database.get_db("alice")
    next(generator)
    with pytest.raises(RuntimeError):
        generator.throw(RuntimeError("endpoint failed"))
    assert sent == []   # an exception inside the request skips the commit and the flag


# ---- Lambda handler -------------------------------------------------------------------------------------

def test_force_comes_only_from_a_direct_invoke():
    assert embed_worker.wants_force({"force": True}) is True
    assert embed_worker.wants_force({"force": "true"}) is False
    assert embed_worker.wants_force({}) is False
    assert embed_worker.wants_force(None) is False
    # an SQS delivery (an S3 flag) can never request a forced re-embed
    assert embed_worker.wants_force({"Records": [{"eventSource": "aws:sqs"}], "force": True}) is False


@pytest.fixture
def handler_env(monkeypatch):
    monkeypatch.setattr(embed_worker, "_engine", object())
    monkeypatch.setattr(embed_worker, "_embedder", object())
    monkeypatch.delenv("EMBED_BATCH_JOBS", raising=False)
    written = []
    monkeypatch.setattr(embed_worker.flag, "write_flag", lambda **kw: written.append(1) or True)
    return written


def run_handler(monkeypatch, result, event=None):
    seen = {}

    def fake_run_pass(engine, embedder, **kwargs):
        seen.update(kwargs)
        return result

    monkeypatch.setattr(embed_worker, "run_pass", fake_run_pass)
    context = SimpleNamespace(get_remaining_time_in_millis=lambda: 900_000)
    return embed_worker.handler(event if event is not None else {}, context), seen


def test_handler_chains_only_when_time_ran_out_with_progress(monkeypatch, handler_env):
    out, seen = run_handler(monkeypatch, PassResult(remaining=True, progress=3))
    assert out["chained"] is True and handler_env == [1]
    assert seen["force"] is False and seen["model"] == embedder_model_name()


@pytest.mark.parametrize("result", [PassResult(remaining=True, progress=0),   # stuck rows: no endless chain
                                    PassResult(remaining=False, progress=5),  # finished
                                    PassResult(busy=True, remaining=True, progress=2)])
def test_handler_does_not_chain_otherwise(monkeypatch, handler_env, result):
    out, _ = run_handler(monkeypatch, result)
    assert out["chained"] is False and handler_env == []


def test_handler_ignores_the_event_contents_but_honours_force_and_budgets_time(monkeypatch, handler_env):
    _, seen = run_handler(monkeypatch, PassResult(), event={"Records": [{"body": "anything", "force": True}]})
    assert seen["force"] is False
    _, seen = run_handler(monkeypatch, PassResult(), event={"force": True})
    assert seen["force"] is True
    assert seen["deadline"] > 0


# ---- in-process embedder --------------------------------------------------------------------------------

class StubBackend:
    model_id = "stub/model"
    dimensions = 3

    def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


def test_embedder_loads_the_model_only_on_first_use():
    loads = []

    def factory():
        loads.append(1)
        return StubBackend()

    embedder = embed_worker.LazyBackendEmbedder(factory)
    assert loads == []                                    # constructing it, or a run with nothing to do, loads nothing
    result = embedder.embed(["a", "b"])
    embedder.embed(["c"])
    assert loads == [1]
    assert result.model == "stub/model" and result.embeddings == ((1.0, 0.0, 0.0), (1.0, 0.0, 0.0))


@pytest.mark.parametrize("texts", [[], [""], ["  "], ["ok", " "]])
def test_embedder_rejects_blank_input(texts):
    with pytest.raises(ValueError):
        embed_worker.LazyBackendEmbedder(StubBackend).embed(texts)


def test_embedder_rejects_text_over_the_limit():
    with pytest.raises(ValueError):
        embed_worker.LazyBackendEmbedder(StubBackend, max_chars=5).embed(["too long"])


# ---- role statements ------------------------------------------------------------------------------------

def test_grant_embedder_is_a_no_op_without_the_role():
    connection = MagicMock()
    connection.scalar.return_value = None
    assert db_role.grant_embedder(connection) is False
    connection.execute.assert_not_called()


def test_grant_embedder_is_least_privilege():
    connection = MagicMock()
    connection.scalar.side_effect = [1, "jobhunter"]   # the role exists, current database
    assert db_role.grant_embedder(connection) is True
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    text = "\n".join(statements)
    assert 'GRANT SELECT ON jobs, profiles, profile_versions, preferences TO "jobhunter_embedder"' in text
    assert 'GRANT SELECT, INSERT, UPDATE ON job_embeddings, profile_embeddings TO "jobhunter_embedder"' in text
    assert 'CREATE POLICY embedder_list_users ON profiles FOR SELECT TO "jobhunter_embedder" USING (true)' in text
    # nothing broader: no superuser or RLS-bypass attribute, no table-wide or write grant outside the two tables
    assert "BYPASSRLS" not in text and "SUPERUSER" not in text and "ALL TABLES" not in text and "ALL PRIVILEGES" not in text
    assert "DELETE" not in text
    # the only policy touches profiles, and it is read-only
    policies = [s for s in statements if s.startswith("CREATE POLICY")]
    assert len(policies) == 1 and " ON profiles FOR SELECT " in policies[0]
