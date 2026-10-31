from __future__ import annotations

from datetime import datetime, timezone
import itertools
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from job_hunter import import_jobs
from job_hunter.ingestion import dedup

from tests.test_import_jobs import FakeJob, MemoryRepository, record

FIXTURE = Path(__file__).parent / "fixtures" / "dedup_pairs.json"


def posting(case_row, number):
    return SimpleNamespace(
        id=UUID(int=number), canonical_job_id=None, also_seen_on=None, posted_at=None,
        company=case_row["company"], title=case_row["title"], location=case_row["location"],
        match_key=dedup.match_key(case_row["company"], case_row["title"], case_row["location"]), **{
            key: case_row[key] for key in ("source", "source_board", "description", "source_url")})


def make(source, number, *, company="Stripe", title="Data Engineer", location="Singapore", description="", url=None, posted=None):
    return SimpleNamespace(
        id=UUID(int=number), source=source, source_board=source, source_url=url or f"https://{source}.example/{number}",
        company=company, title=title, location=location, description=description, posted_at=posted,
        match_key=dedup.match_key(company, title, location), canonical_job_id=None, also_seen_on=None)


LONG = " ".join(f"word{i}" for i in range(80))


# --- normalisation ---------------------------------------------------------------------------------------

def test_company_names_lose_legal_words_and_punctuation():
    assert dedup.normalise_company("Stripe Singapore Pte. Ltd.") == "stripe"
    assert dedup.normalise_company("STRIPE, Inc.") == "stripe"
    assert dedup.normalise_company("Café Réunion Co.") == "cafe reunion"
    assert dedup.normalise_company("Pte Ltd") == "pte ltd"          # a name made only of legal words is kept as it is


def test_titles_keep_their_words_so_levels_stay_different():
    assert dedup.normalise_title("Product Designer (Onboarding)") == dedup.normalise_title("Product Designer - Onboarding")
    assert dedup.normalise_title("Senior Data Engineer") != dedup.normalise_title("Data Engineer")


def test_every_singapore_location_is_the_same_place():
    assert dedup.normalise_location("Tanjong Pagar, Singapore") == dedup.normalise_location("Singapore") == "singapore"
    assert dedup.normalise_location("London") == "london"


def test_no_employer_or_title_means_no_key():
    assert dedup.match_key(None, "Data Engineer", "Singapore") is None
    assert dedup.match_key("Stripe", "", "Singapore") is None
    assert dedup.match_key("Stripe", "Data Engineer", None) == "stripe|data engineer|"


# --- the labelled set: precision and recall ---------------------------------------------------------------

def judged():
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [(case, dedup.same_posting(posting(case["a"], 1), posting(case["b"], 2))) for case in cases]


def test_the_labelled_set_has_no_false_merges_and_finds_the_duplicates():
    results = judged()
    true_positive = sum(1 for case, said in results if said and case["same"])
    false_positive = [case["name"] for case, said in results if said and not case["same"]]
    false_negative = [case["name"] for case, said in results if not said and case["same"]]
    precision = true_positive / max(1, true_positive + len(false_positive))
    recall = true_positive / max(1, true_positive + len(false_negative))
    # Reported in the project report: the labelled set (backend/tests/fixtures/dedup_pairs.json) is the dedup accuracy evidence.
    print(f"dedup labelled set: {len(results)} pairs, precision {precision:.2f}, recall {recall:.2f}, "
          f"threshold {dedup.SIMILARITY_THRESHOLD}")
    assert false_positive == []                    # a wrong merge hides a real job: never acceptable
    assert false_negative == []
    assert len(results) >= 16


def test_the_threshold_leaves_room_on_both_sides():
    scores = [(case["same"], dedup.description_similarity(case["a"]["description"], case["b"]["description"]))
              for case in json.loads(FIXTURE.read_text(encoding="utf-8"))
              if case["a"]["source"] != case["b"]["source"] and case["a"]["company"] and
              dedup.match_key(case["a"]["company"], case["a"]["title"], case["a"]["location"]) ==
              dedup.match_key(case["b"]["company"], case["b"]["title"], case["b"]["location"])]
    duplicates = [score for same, score in scores if same and score > 0]
    others = [score for same, score in scores if not same]
    assert min(duplicates) > dedup.SIMILARITY_THRESHOLD + 0.05
    assert max(others) < dedup.SIMILARITY_THRESHOLD - 0.05


def test_a_short_text_proves_nothing():
    assert dedup.description_similarity("See careers page.", "See careers page.") == 0.0


# --- linking ---------------------------------------------------------------------------------------------

def test_authority_decides_the_canonical_row_whatever_the_order():
    rows = [make("adzuna", 1, description=LONG), make("mycareersfuture", 2, description=LONG), make("greenhouse", 3, description=LONG)]
    for ordering in itertools.permutations(rows):
        for row in rows:
            row.canonical_job_id, row.also_seen_on = None, None
        dedup.relink(list(ordering))
        by_source = {row.source: row for row in rows}
        assert by_source["greenhouse"].canonical_job_id is None
        assert by_source["mycareersfuture"].canonical_job_id == by_source["greenhouse"].id
        assert by_source["adzuna"].canonical_job_id == by_source["greenhouse"].id
        assert [item["source"] for item in by_source["greenhouse"].also_seen_on] == ["mycareersfuture", "adzuna"]
        assert by_source["adzuna"].also_seen_on == []


def test_the_earlier_posting_wins_between_equal_authorities():
    early, late = datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 10, 1, tzinfo=timezone.utc)
    a = make("greenhouse", 5, description=LONG, url="https://a.example/1", posted=late)
    b = make("lever", 4, description=LONG, url="https://b.example/1", posted=early)
    dedup.relink([a, b])
    assert b.canonical_job_id is None and a.canonical_job_id == b.id


def test_a_new_better_source_takes_over_without_deleting_anything():
    adzuna = make("adzuna", 1, description=LONG)
    mcf = make("mycareersfuture", 2, description=LONG)
    dedup.relink([adzuna, mcf])
    assert adzuna.canonical_job_id == mcf.id and mcf.canonical_job_id is None
    greenhouse = make("greenhouse", 3, description=LONG)
    dedup.relink([adzuna, mcf, greenhouse])
    assert greenhouse.canonical_job_id is None and mcf.canonical_job_id == greenhouse.id and adzuna.canonical_job_id == greenhouse.id


def test_a_row_that_stops_matching_is_unlinked():
    first, second = make("greenhouse", 1, description=LONG), make("mycareersfuture", 2, description=LONG)
    dedup.relink([first, second])
    assert second.canonical_job_id == first.id
    second.description = "Entirely different text. " * 20
    dedup.relink([first, second])
    assert second.canonical_job_id is None and first.also_seen_on == []


def test_a_closed_row_never_hides_an_open_copy():
    greenhouse, mcf = make("greenhouse", 1, description=LONG), make("mycareersfuture", 2, description=LONG)
    greenhouse.status = "closed"
    dedup.relink([greenhouse, mcf])
    assert mcf.canonical_job_id is None and greenhouse.canonical_job_id == mcf.id
    greenhouse.status = "open"          # listed again: the employer's own board is the canonical row again
    dedup.relink([greenhouse, mcf])
    assert greenhouse.canonical_job_id is None and mcf.canonical_job_id == greenhouse.id


def test_rows_of_one_source_are_never_linked():
    a, b = make("greenhouse", 1, description=LONG), make("greenhouse", 2, description=LONG)
    dedup.relink([a, b])
    assert a.canonical_job_id is None and b.canonical_job_id is None


def test_relink_all_backfills_keys_and_links():
    rows = [make("greenhouse", 1, company="Stripe", description=LONG), make("mycareersfuture", 2, company="Stripe Singapore Pte Ltd", description=LONG),
            make("lever", 3, company="Acme", title="Analyst", description=LONG)]
    for row in rows:
        row.match_key = None
    counts = dedup.relink_all(rows)
    assert all(row.match_key for row in rows)
    assert rows[1].canonical_job_id == rows[0].id and rows[2].canonical_job_id is None
    assert counts["linked"] == 1 and counts["keyed"] == 3


# --- the importer ----------------------------------------------------------------------------------------

class GroupRepository(MemoryRepository):
    """MemoryRepository that also supports the duplicate lookup, with ids like a flushed database row."""
    def add(self, job):
        job.id = UUID(int=len(self.added) + 100)
        job.canonical_job_id = job.also_seen_on = None
        super().add(job)

    def find_by_match_key(self, key):
        return [job for job in self.jobs.values() if job.match_key == key]


def source_record(source, external_id, employer, board="b", **overrides):
    return record(source=source, source_board=board, external_id=external_id, employer=employer, description=LONG,
                  dedup_key=f"{source}:{board}:{external_id}", source_url=f"https://{source}.example/{external_id}", **overrides)


def test_importing_two_sources_links_them_and_a_reimport_changes_nothing():
    repo = GroupRepository()
    first = import_jobs.upsert_records(repo, [source_record("greenhouse", "1", "Stripe")], job_model=FakeJob)
    second = import_jobs.upsert_records(repo, [source_record("mycareersfuture", "2", "Stripe Singapore Pte Ltd", board="sg",
                                                             location="Tanjong Pagar, Singapore")], job_model=FakeJob)
    assert (first.new, first.linked) == (1, 0) and (second.new, second.linked) == (1, 2)   # the duplicate gets its link, the canonical row its also_seen_on
    ats, gov = repo.jobs[("greenhouse", "b", "1")], repo.jobs[("mycareersfuture", "sg", "2")]
    assert ats.canonical_job_id is None and gov.canonical_job_id == ats.id
    assert [item["source"] for item in ats.also_seen_on] == ["mycareersfuture"]
    again = import_jobs.upsert_records(repo, [source_record("greenhouse", "1", "Stripe"),
                                              source_record("mycareersfuture", "2", "Stripe Singapore Pte Ltd", board="sg",
                                                            location="Tanjong Pagar, Singapore")], job_model=FakeJob)
    assert (again.new, again.updated, again.unchanged, again.linked) == (0, 0, 2, 0)
    assert len(repo.added) == 2


def test_the_link_key_is_set_on_old_rows_without_queuing_a_re_embedding():
    repo = GroupRepository()
    import_jobs.upsert_records(repo, [source_record("greenhouse", "1", "Stripe")], job_model=FakeJob)
    old = repo.jobs[("greenhouse", "b", "1")]
    old.match_key = None                       # a row imported before de-duplication existed
    stamp = old.updated_at
    stats = import_jobs.upsert_records(repo, [source_record("greenhouse", "1", "Stripe")], job_model=FakeJob)
    assert stats.unchanged == 1 and old.match_key and old.updated_at == stamp


def test_an_edited_listing_is_relinked_under_its_new_key():
    repo = GroupRepository()
    import_jobs.upsert_records(repo, [source_record("greenhouse", "1", "Stripe"), source_record("lever", "2", "Stripe")], job_model=FakeJob)
    lever = repo.jobs[("lever", "b", "2")]
    assert lever.canonical_job_id == repo.jobs[("greenhouse", "b", "1")].id
    import_jobs.upsert_records(repo, [source_record("lever", "2", "Stripe", title="Data Scientist")], job_model=FakeJob)
    assert lever.canonical_job_id is None
    assert repo.jobs[("greenhouse", "b", "1")].also_seen_on == []


def test_a_repository_without_the_group_lookup_still_imports():
    stats = import_jobs.upsert_records(MemoryRepository(), [source_record("greenhouse", "1", "Stripe")], job_model=FakeJob)
    assert (stats.new, stats.linked) == (1, 0)
