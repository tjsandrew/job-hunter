from collections.abc import Generator
from pathlib import Path
import logging
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from job_hunter.config import settings
from job_hunter.domain.models import User
from job_hunter.domain.identity import DEV_USERS

engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=3, max_overflow=0)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def get_db(dev_identity: str) -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        session.begin()
        user_id, _ = DEV_USERS[dev_identity]
        session.execute(text("SELECT set_config('app.user_id', :user_id, true)"),
                        {"user_id": str(user_id)})
        user = session.get(User, user_id)
        if user is None:
            raise ValueError("Development identity has not been seeded")
        session.info["current_user"] = user
        yield session
        session.commit()
        for file_path in session.info.get("profile_upload_cleanup", []):
            try:
                Path(file_path).unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).exception("Profile upload cleanup failed after commit")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
