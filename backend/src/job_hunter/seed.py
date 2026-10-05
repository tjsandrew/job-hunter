import os
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from job_hunter.config import settings
from job_hunter.domain.models import Base, User, Profile, Preference, Job
from job_hunter.domain.identity import DEV_USERS
from job_hunter.demo import PROFILE

def seed():
    url = os.getenv("MIGRATION_DATABASE_URL") or settings.database_url
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
      with db.begin():
        for key, (user_id, name) in DEV_USERS.items():
            db.execute(text("SELECT set_config('app.user_id', :user_id, true)"),
                       {"user_id": str(user_id)})
            user = db.get(User, user_id)
            if not user:
                db.add(User(id=user_id, auth_subject=key, display_name=name,
                            plan="premium" if key == "bob" else "free"))
                db.flush()
                db.add(Profile(user_id=user_id, draft=PROFILE if key == "alice" else {"display_name": name, "skills": [],
                    "experience": [], "education": [], "projects": []}, revision=1))
                db.add(Preference(user_id=user_id, data={"roles": [], "locations": ["Singapore"],
                    "work_modes": [], "seniority": None, "salary_min": None,
                    "salary_currency": "SGD", "salary_period": "year"}, revision=1))
        jobs = [
            ("Backend Engineer", "Meridian Labs", "Singapore", "hybrid", ["Python", "PostgreSQL"], "Build APIs and data services with a collaborative engineering team."),
            ("Product Data Analyst", "Harbour Analytics", "Singapore", "onsite", ["SQL", "Analytics"], "Turn product data into clear experiments and recommendations."),
            ("Frontend Developer", "Northstar Pte Ltd", "Remote", "remote", ["React", "TypeScript"], "Create accessible web experiences for customers across Asia."),
        ]
        for title, company, location, mode, skills, description in jobs:
            if not db.scalar(select(Job).where(Job.title == title, Job.company == company)):
                db.add(Job(title=title, company=company, location=location, work_mode=mode,
                    skills=skills, description=description, source="synthetic", url="https://example.invalid/jobs"))

if __name__ == "__main__":
    seed()
