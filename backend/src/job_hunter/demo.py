"""One coherent fictional candidate for the local demonstration only."""
PROFILE = {
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
