import pytest

from job_hunter.embedding import (
    JOB_TEXT_VERSION,
    STATUS_FAILED,
    STATUS_NO_CONTENT,
    STATUS_PENDING,
    STATUS_READY,
    STATUS_UNCHANGED,
    EmbedderUnavailable,
    EmbeddingRecord,
    EmbeddingResult,
    InMemoryEmbeddingStore,
    InvalidEmbeddingResponse,
    JobEmbedRequest,
    JobTextInput,
    ProfileEmbedRequest,
    build_job_text,
    embed_job,
    embed_jobs,
    embed_profile,
    embed_profiles,
)
from job_hunter.embedding.stores import StoredEmbeddingState

MODEL = "fake-model"
JOB_KEY = ("j1", JOB_TEXT_VERSION)


class FakeEmbedder:
    def __init__(self, model=MODEL, error=None, bad_count=False):
        self.model, self.error, self.bad_count = model, error, bad_count
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        if self.error:
            raise self.error
        vectors = [tuple(1.0 if j == (len(t) % 512) else 0.0 for j in range(512)) for t in texts]
        if self.bad_count:
            vectors = vectors[:-1]
        return EmbeddingResult(model=self.model, embeddings=tuple(vectors))


def job(job_id="j1", title="Backend Engineer", description="Responsibilities\n" + "Build and run APIs for payments. " * 6,
        **kwargs):
    return JobEmbedRequest(job_id=job_id, job=JobTextInput(title=title, description=description), **kwargs)


SNAPSHOT = {"headline": "Junior backend engineer", "summary": "Builds APIs.", "skills": ["Python", "SQL"],
            "experience": [{"role": "Intern", "skills": []}], "bullets": [{"text": "Built an API"}]}


def profile(version_id="p1", roles=("Backend Engineer",), snapshot=None):
    return ProfileEmbedRequest(profile_version_id=version_id, snapshot=snapshot if snapshot is not None else SNAPSHOT,
                               target_roles=list(roles))


def run_job(request=None, embedder=None, store=None, **kwargs):
    embedder = embedder or FakeEmbedder()
    store = store if store is not None else InMemoryEmbeddingStore()
    return embed_job(request or job(), embedder=embedder, store=store, **kwargs), embedder, store


# ---- jobs -------------------------------------------------------------------------------------

def test_job_is_embedded_and_stored_with_its_metadata():
    outcome, embedder, store = run_job()
    assert outcome.status == STATUS_READY and outcome.model == MODEL and outcome.reason is None
    assert embedder.calls == [[build_job_text(job().job).text]]
    record = store.records[JOB_KEY]
    assert record.status == STATUS_READY and record.model == MODEL and record.dimensions == 512
    assert len(record.vector) == 512 and record.text_version == JOB_TEXT_VERSION and len(record.input_hash) == 64


def test_calling_twice_does_nothing_the_second_time():
    store = InMemoryEmbeddingStore()
    first, embedder, _ = run_job(store=store)
    second, _, _ = run_job(store=store, embedder=embedder)
    assert first.status == STATUS_READY and second.status == STATUS_UNCHANGED
    assert len(embedder.calls) == 1


def test_changed_text_model_or_force_triggers_a_new_embedding():
    store = InMemoryEmbeddingStore()
    _, embedder, _ = run_job(store=store)
    changed = job(description="Responsibilities\n" + "Design data pipelines for analytics teams. " * 5)
    assert run_job(changed, embedder, store)[0].status == STATUS_READY             # text changed
    assert run_job(changed, embedder, store, expected_model="other-model")[0].status == STATUS_READY  # model changed
    assert run_job(changed, embedder, store, expected_model=MODEL)[0].status == STATUS_UNCHANGED
    assert run_job(changed, embedder, store, force=True)[0].status == STATUS_READY
    assert len(embedder.calls) == 4


def test_a_row_for_an_older_text_version_does_not_count_and_is_kept():
    store = InMemoryEmbeddingStore()
    old = EmbeddingRecord(status=STATUS_READY, model=MODEL, dimensions=512, text_version="job-v0",
                          input_hash="abc", vector=(0.0,) * 512)
    store.save("j1", old)
    outcome, embedder, _ = run_job(store=store)
    assert outcome.status == STATUS_READY and len(embedder.calls) == 1
    assert ("j1", "job-v0") in store.records and JOB_KEY in store.records       # both formats coexist


def test_embedder_unavailable_gives_pending_without_a_usable_vector_then_recovers():
    store = InMemoryEmbeddingStore()
    outcome, _, _ = run_job(embedder=FakeEmbedder(error=EmbedderUnavailable("down")), store=store)
    assert outcome.status == STATUS_PENDING and outcome.reason == "embedding service unavailable"
    record = store.records[JOB_KEY]
    assert record.status == STATUS_PENDING and record.vector is None
    assert run_job(store=store)[0].status == STATUS_READY                  # a later retry succeeds


def test_stale_vector_is_cleared_when_the_text_changes_and_the_embedder_is_down():
    store = InMemoryEmbeddingStore()
    run_job(store=store)
    assert store.records[JOB_KEY].vector is not None
    changed = job(description="Responsibilities\n" + "Something quite different happens here. " * 5)
    outcome, _, _ = run_job(changed, FakeEmbedder(error=EmbedderUnavailable("down")), store)
    assert outcome.status == STATUS_PENDING and store.records[JOB_KEY].vector is None


@pytest.mark.parametrize("error,bad_count", [(InvalidEmbeddingResponse("bad"), False), (RuntimeError("boom"), False), (None, True)])
def test_unusable_or_unexpected_embedder_results_give_failed_not_an_exception(error, bad_count):
    outcome, _, store = run_job(embedder=FakeEmbedder(error=error, bad_count=bad_count))
    assert outcome.status == STATUS_FAILED and store.records[JOB_KEY].vector is None


def test_failure_reasons_never_contain_the_input_text():
    secret = "SECRET-CV-TEXT"
    outcome, _, _ = run_job(embedder=FakeEmbedder(error=RuntimeError(f"cannot embed {secret}")))
    assert secret not in (outcome.reason or "") and outcome.reason == "unexpected embedder error: RuntimeError"


def test_blank_title_has_no_content_and_never_calls_the_embedder():
    outcome, embedder, store = run_job(job(title="   "))
    assert outcome.status == STATUS_NO_CONTENT and embedder.calls == []
    assert store.records[JOB_KEY].status == STATUS_NO_CONTENT and store.records[JOB_KEY].vector is None


class BrokenStore(InMemoryEmbeddingStore):
    def __init__(self, fail_on):
        super().__init__()
        self.fail_on = fail_on

    def get_state(self, key, text_version):
        if self.fail_on == "get_state":
            raise ConnectionError("db down with SECRET-ROW")
        return super().get_state(key, text_version)

    def save(self, key, record):
        if self.fail_on == "save":
            raise ConnectionError("db down")
        super().save(key, record)


@pytest.mark.parametrize("fail_on", ["get_state", "save"])
def test_storage_errors_give_failed_without_leaking_details(fail_on):
    outcome, _, _ = run_job(store=BrokenStore(fail_on))
    assert outcome.status == STATUS_FAILED and outcome.reason == "storage error: ConnectionError"


# ---- batches ----------------------------------------------------------------------------------

def test_batch_skips_unchanged_items_keeps_order_and_splits_into_batches():
    store = InMemoryEmbeddingStore()
    embedder = FakeEmbedder()
    descriptions = {f"j{i}": "Responsibilities\n" + f"Work item number {i} for the platform team. " * 6 for i in range(5)}
    requests = [job(job_id=k, description=v) for k, v in descriptions.items()]
    embed_job(requests[1], embedder=embedder, store=store)      # j1 already done
    embedder.calls.clear()
    outcomes = embed_jobs(requests, embedder=embedder, store=store, batch_size=2)
    assert [o.key for o in outcomes] == list(descriptions)
    assert [o.status for o in outcomes] == [STATUS_READY, STATUS_UNCHANGED, STATUS_READY, STATUS_READY, STATUS_READY]
    assert [len(c) for c in embedder.calls] == [2, 2]


def test_a_failing_batch_only_affects_its_own_items():
    class FlakyEmbedder(FakeEmbedder):
        def embed(self, texts):
            if len(self.calls) == 1:
                self.calls.append(list(texts))
                raise EmbedderUnavailable("down")
            return super().embed(texts)

    requests = [job(job_id=f"j{i}", description="Responsibilities\n" + f"Item {i} needs delivery work here. " * 6)
                for i in range(4)]
    outcomes = embed_jobs(requests, embedder=FlakyEmbedder(), store=InMemoryEmbeddingStore(), batch_size=2)
    assert [o.status for o in outcomes] == [STATUS_READY, STATUS_READY, STATUS_PENDING, STATUS_PENDING]


def test_invalid_batch_size_is_a_programming_error():
    for size in (0, 65):
        with pytest.raises(ValueError):
            embed_jobs([job()], embedder=FakeEmbedder(), store=InMemoryEmbeddingStore(), batch_size=size)


# ---- profiles ---------------------------------------------------------------------------------

def test_profile_is_embedded_with_its_target_roles_in_the_text():
    embedder, store = FakeEmbedder(), InMemoryEmbeddingStore()
    outcome = embed_profile(profile(), embedder=embedder, store=store)
    assert outcome.status == STATUS_READY
    record = store.records[("p1", "profile-v2")]
    assert record.text_version == "profile-v2"
    assert embedder.calls[0][0].startswith("Target role: Backend Engineer")


def test_changing_the_target_role_re_embeds_but_the_same_profile_does_not():
    embedder, store = FakeEmbedder(), InMemoryEmbeddingStore()
    embed_profile(profile(), embedder=embedder, store=store)
    assert embed_profile(profile(), embedder=embedder, store=store).status == STATUS_UNCHANGED
    assert embed_profile(profile(roles=("Data Engineer",)), embedder=embedder, store=store).status == STATUS_READY
    assert len(embedder.calls) == 2


def test_empty_profile_has_no_content():
    embedder, store = FakeEmbedder(), InMemoryEmbeddingStore()
    outcome = embed_profile(profile(snapshot={"name": "Alice"}, roles=()), embedder=embedder, store=store)
    assert outcome.status == STATUS_NO_CONTENT and embedder.calls == []
    assert store.records[("p1", "profile-v2")].status == STATUS_NO_CONTENT


def test_profiles_batch_works_like_jobs():
    embedder, store = FakeEmbedder(), InMemoryEmbeddingStore()
    outcomes = embed_profiles([profile("p1"), profile("p2", roles=("Data Engineer",))], embedder=embedder, store=store)
    assert [o.status for o in outcomes] == [STATUS_READY, STATUS_READY] and len(embedder.calls) == 1


def test_in_memory_store_roundtrip():
    store = InMemoryEmbeddingStore()
    assert store.get_state("x", "job-v1") is None
    run_job(store=store)
    state = store.get_state("j1", JOB_TEXT_VERSION)
    assert isinstance(state, StoredEmbeddingState) and state.status == STATUS_READY and state.model == MODEL
    assert store.get_state("j1", "job-v0") is None


def test_job_text_version_can_be_chosen_and_formats_are_stored_side_by_side():
    store = InMemoryEmbeddingStore()
    embedder = FakeEmbedder()
    desc = "Responsibilities\n" + "Build and run APIs for payments. " * 6
    request = job(description=desc)
    assert embed_job(request, embedder=embedder, store=store).status == STATUS_READY
    assert embed_job(request, embedder=embedder, store=store, text_version="job-v1").status == STATUS_READY
    assert store.get_state("j1", "job-v2") is not None and store.get_state("j1", "job-v1") is not None
    assert store.records[("j1", "job-v1")].input_hash != store.records[("j1", "job-v2")].input_hash
    bad = embed_job(request, embedder=embedder, store=store, text_version="job-v9")
    assert bad.status == STATUS_NO_CONTENT and "unknown job text version" in (bad.reason or "")
