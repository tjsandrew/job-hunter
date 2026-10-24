from datetime import datetime, timezone

from job_hunter.preparation import ai_tailoring
from job_hunter.preparation.allowance import LIMIT, limit_for, month_label, month_start


def test_the_month_follows_the_singapore_calendar():
    # 31 Oct 17:00 UTC is already 1 Nov 01:00 in Singapore.
    now = datetime(2026, 10, 31, 17, 0, tzinfo=timezone.utc)
    assert month_label(now) == "2026-11"
    start = month_start(now)
    assert (start.day, start.hour, start.minute) == (1, 0, 0)


def test_a_mid_month_moment_stays_in_its_month():
    assert month_label(datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)) == "2026-10"


def test_tailoring_and_fit_share_one_limit():
    assert LIMIT == 5 == ai_tailoring.LIMIT


def test_premium_users_get_more_slots_and_unknown_plans_get_the_free_limit():
    assert limit_for("free") == 5
    assert limit_for("premium") == 50
    assert limit_for(None) == limit_for("something-else") == LIMIT
