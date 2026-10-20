from collections.abc import Generator
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from job_hunter.config import settings
from job_hunter.domain.models import User
from job_hunter.domain.identity import DEV_USERS
from job_hunter.adapters.auth import CloudIdentity
from job_hunter.adapters import storage
from sqlalchemy.dialects.postgresql import insert
from job_hunter.adapters.aws_config import iam_engine

engine = (iam_engine(settings.database_host, settings.database_name, settings.database_username)
          if settings.database_auth == "iam" else create_engine(settings.database_url, pool_pre_ping=True,
          pool_size=settings.db_pool_size, max_overflow=0, hide_parameters=True))
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def get_db(dev_identity: str | CloudIdentity) -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        session.begin()
        user_id = dev_identity.user_id if isinstance(dev_identity, CloudIdentity) else DEV_USERS[dev_identity][0]
        session.execute(text("SELECT set_config('app.user_id', :user_id, true)"),
                        {"user_id": str(user_id)})
        if isinstance(dev_identity, CloudIdentity):
            session.execute(insert(User).values(id=user_id, auth_subject=dev_identity.subject,
                            display_name=dev_identity.display_name, plan="free").on_conflict_do_nothing())
        user = session.get(User, user_id)
        if user is None:
            raise ValueError("Development identity has not been seeded")
        session.info["current_user"] = user
        yield session
        session.commit()
        for file_path in session.info.get("profile_upload_cleanup", []):
            try:
                storage.delete(file_path)
            except Exception:
                logging.getLogger(__name__).exception("Profile upload cleanup failed after commit")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
