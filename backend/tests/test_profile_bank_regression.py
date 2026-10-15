"""Ranking remains identical with bank storage; the ranker itself is unchanged."""
import json
from pathlib import Path

from job_hunter.demo import PROFILE, PROFILE_ITEMS
from job_hunter.profile_bank import assemble_profile_snapshot, validate_item_data
from job_hunter.profile_bank.migration import migrate_legacy_profile
from job_hunter.recommendations import rank_jobs


def test_migrated_legacy_and_richer_demo_keep_recorded_ranking_order_and_reasons():
    before = json.loads((Path(__file__).parent / "fixtures/profile_bank_recommendations_before.json").read_text())
    basics, migrated = migrate_legacy_profile(before["profile"], "demo")
    snapshot = assemble_profile_snapshot(basics, migrated, 1)
    assert rank_jobs(before["jobs"], snapshot, before["preferences"]) == before["expected"]
    demo = []
    positions = {}
    for index, item in enumerate(PROFILE_ITEMS):
        kind = item["kind"]
        position = positions.get(kind, 0)
        demo.append({**item, "id": f"demo-{index}", "position": position,
                     "data": validate_item_data(kind, item["data"])})
        positions[kind] = position + 1
    richer_snapshot = assemble_profile_snapshot(PROFILE, demo, 1)
    assert rank_jobs(before["jobs"], richer_snapshot, before["preferences"]) == before["expected"]
