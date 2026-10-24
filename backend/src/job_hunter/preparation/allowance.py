"""One AI slot per user and job per Singapore calendar month, shared by AI tailoring and fit analysis."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_hunter.domain.models import AiTailorUse, now_utc

LIMITS = {"free": 5, "premium": 50}
LIMIT = LIMITS["free"]  # the default every user starts on
SINGAPORE = timezone(timedelta(hours=8))


def limit_for(plan: str | None) -> int:
    """Monthly slots for a plan. An unknown or missing plan gets the free limit."""
    return LIMITS.get(plan or "free", LIMIT)


def month_start(now: datetime | None = None) -> datetime:
    """Midnight on the first day of the current Singapore month."""
    local = (now or now_utc()).astimezone(SINGAPORE)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_label(now: datetime | None = None) -> str:
    return month_start(now).strftime("%Y-%m")


def uses(db: Session, user_id: UUID, now: datetime | None = None) -> int:
    return db.scalar(select(func.count()).select_from(AiTailorUse)
                     .where(AiTailorUse.user_id == user_id, AiTailorUse.created_at >= month_start(now)))


def has_slot(db: Session, user_id: UUID, job_id: UUID, now: datetime | None = None) -> bool:
    """True when this job already used its slot this month, so using it again costs nothing."""
    row = db.get(AiTailorUse, (user_id, job_id))
    return row is not None and row.created_at >= month_start(now)


def can_spend(db: Session, user_id: UUID, job_id: UUID, plan: str | None = None, now: datetime | None = None,
              reserved: int = 0) -> bool:
    """``reserved`` counts analyses still running: they will take a slot when they finish, so they count already."""
    return has_slot(db, user_id, job_id, now) or uses(db, user_id, now) + reserved < limit_for(plan)


def spend(db: Session, user_id: UUID, job_id: UUID, now: datetime | None = None) -> None:
    """Use this job's slot for the month. A row left from an earlier month is refreshed, not duplicated."""
    row = db.get(AiTailorUse, (user_id, job_id))
    if row is None:
        db.add(AiTailorUse(user_id=user_id, job_id=job_id, created_at=now or now_utc()))
    elif row.created_at < month_start(now):
        row.created_at = now or now_utc()
