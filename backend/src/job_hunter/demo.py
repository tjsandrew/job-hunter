"""One coherent fictional candidate for the local demonstration only."""
from job_hunter.profile_bank.skills import infer_skill_category

LEGACY_PROFILE = {
    "name": "Alex Tan", "display_name": "Alex Tan", "email": "alex.tan@example.invalid",
    "phone": "", "location": "Singapore", "headline": "Data & Backend Engineer",
    "summary": "Data and backend engineer with four years of experience building reliable Python services, SQL data pipelines and analytics products. Combines PostgreSQL performance tuning, experiment analysis and practical machine learning with clear stakeholder communication.",
    "skills": ["Python", "SQL", "PostgreSQL", "FastAPI", "Docker", "Git", "pandas", "scikit-learn", "Tableau", "Data modelling", "Unit testing"],
    "experience": [
        {"role": "Data & Backend Engineer", "company": "Harbour Metrics (fictional)", "dates": "2023–Present"},
        {"role": "Data Analyst", "company": "Straits Commerce (fictional)", "dates": "2022–2023"}
    ],
    "education": [{"degree": "BSc in Computer Science", "school": "Example University (fictional)", "dates": "2018–2022"}],
    "projects": [{"name": "Customer retention analytics"}, {"name": "Job discovery data pipeline"}]
}
PROFILE = {key: value for key, value in LEGACY_PROFILE.items()
           if key not in {"skills", "experience", "education", "projects"}}
PROFILE_ITEMS = [
    {"kind": "experience", "data": {
        "title": "Data & Backend Engineer", "organisation": "Harbour Metrics (fictional)",
        "start": "2023", "end": None, "current": True, "bullets": [
            {"id": "b_demo_backend", "text": "Built FastAPI services and PostgreSQL data models with ownership checks and versioned migrations.",
             "tags": ["backend"], "skills": ["Python", "PostgreSQL"], "alternatives": [
                 {"id": "v_demo_technical", "text": "Implemented validated Python APIs, tenant ownership checks and PostgreSQL migrations.", "tags": ["backend"]},
                 {"id": "v_demo_impact", "text": "Made the analytics workspace easier to maintain with tested APIs and repeatable database changes.", "tags": ["data"]}]},
            {"id": "b_demo_data", "text": "Designed incremental SQL pipelines with duplicate detection and data-quality checks.", "tags": ["data"]},
            {"id": "b_demo_leadership", "text": "Introduced shared testing and Docker workflows and documented release practices for the team.", "tags": ["leadership", "backend"]}]}},
    {"kind": "experience", "data": {"title": "Data Analyst", "organisation": "Straits Commerce (fictional)",
        "start": "2022", "end": "2023", "current": False, "bullets": []}},
    {"kind": "education", "data": {"qualification": "BSc in Computer Science", "institution": "Example University (fictional)",
        "start": "2018", "end": "2022", "current": False, "bullets": []}},
    {"kind": "project", "data": {"name": "Customer retention analytics", "bullets": []}},
    {"kind": "project", "data": {"name": "Job discovery data pipeline", "bullets": []}},
    *[{"kind": "skill", "data": {"name": name, "category": infer_skill_category(name)}}
      for name in LEGACY_PROFILE["skills"]],
    {"kind": "custom", "data": {"title": "Community interests", "bullets": [
        {"id": "b_demo_custom", "text": "Organise fictional community coding meetups using synthetic practice datasets.", "tags": ["leadership"]}]}},
]

CONTENT = {
    "name": PROFILE["name"], "email": PROFILE["email"], "phone": "", "location": "Singapore",
    "summary": PROFILE["summary"],
    "sections": [
        {"id": "experience", "title": "Professional experience", "entries": [
            {"id": "engineer", "heading": "Data & Backend Engineer", "subheading": "Harbour Metrics · Singapore (fictional)", "dates": "Jul 2023 – Present", "bullets": [
                "Built FastAPI services and PostgreSQL data models for an internal analytics workspace; added validation, ownership checks and versioned migrations.",
                "Designed incremental SQL pipelines with duplicate detection and data-quality checks, giving analysts consistent daily reporting tables.",
                "Introduced unit and integration tests, Docker development environments and CI checks to make releases repeatable."
            ]},
            {"id": "analyst", "heading": "Data Analyst", "subheading": "Straits Commerce · Singapore (fictional)", "dates": "Jul 2022 – Jun 2023", "bullets": [
                "Developed SQL cohort analyses and Tableau dashboards for customer retention, revenue trends and operational reporting.",
                "Worked with product stakeholders to define metrics and interpret A/B tests; documented assumptions and data limitations."
            ]}
        ]},
        {"id": "projects", "title": "Selected projects", "entries": [
            {"id": "retention", "heading": "Customer retention analytics", "subheading": "Personal portfolio · synthetic dataset", "dates": "2025", "bullets": [
                "Built a pandas and scikit-learn classification pipeline with leakage checks, stratified validation and precision/recall evaluation.",
                "Served model predictions through a tested FastAPI endpoint and packaged the application in Docker."
            ]},
            {"id": "discovery", "heading": "Job discovery data pipeline", "subheading": "Personal portfolio", "dates": "2026", "bullets": [
                "Normalized public employer postings into PostgreSQL with source identifiers, repeatable imports and source freshness timestamps."
            ]}
        ]},
        {"id": "education", "title": "Education", "entries": [
            {"id": "degree", "heading": "BSc in Computer Science", "subheading": "Example University (fictional)", "dates": "2018 – 2022", "bullets": [
                "Focus: databases, software engineering, statistics and machine learning."
            ]}
        ]},
        {"id": "skills", "title": "Technical skills", "entries": [
            {"id": "tools", "heading": "Engineering & analytics", "subheading": "", "dates": "", "bullets": [
                "Python · SQL · PostgreSQL · FastAPI · Docker · Git · pandas · scikit-learn · Tableau",
                "Data modelling · API design · Unit and integration testing · Experiment analysis"
            ]}
        ]}
    ]
}
