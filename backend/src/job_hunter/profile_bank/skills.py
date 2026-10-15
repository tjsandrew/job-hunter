"""Best-effort skill categories for skills that arrive without one."""

# Small, explicit lists: unknown names fall back to "domain" rather than guessing.
_LANGUAGES = {"python", "sql", "java", "javascript", "typescript", "go", "golang", "r", "c", "c++", "c#",
              "kotlin", "swift", "scala", "rust", "ruby", "php", "bash", "shell", "html", "css", "matlab"}
_FRAMEWORKS = {"fastapi", "django", "flask", "react", "vue", "angular", "next.js", "node.js", "express",
               "spring", "spring boot", "pandas", "numpy", "scikit-learn", "pytorch", "tensorflow", "keras",
               "sqlalchemy", "pydantic", "tailwind", ".net"}
_TOOLS = {"postgresql", "postgres", "mysql", "sqlite", "mongodb", "redis", "kafka", "airflow", "docker",
          "kubernetes", "terraform", "git", "github", "gitlab", "aws", "gcp", "azure", "linux", "tableau",
          "power bi", "excel", "jira", "figma", "spark", "snowflake", "dbt", "jenkins", "ci/cd"}
_SOFT = {"communication", "leadership", "mentoring", "teamwork", "stakeholder management",
         "presentation", "negotiation", "problem solving"}


def infer_skill_category(name: str) -> str:
    key = " ".join(str(name).casefold().split())
    for category, names in (("language", _LANGUAGES), ("framework", _FRAMEWORKS),
                            ("tool", _TOOLS), ("soft", _SOFT)):
        if key in names:
            return category
    return "domain"
