from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    auth_mode: str = "local"
    database_url: str = "postgresql+psycopg://jobhunter:jobhunter@localhost:5432/jobhunter"
    auto_create_schema: bool = False
    dev_default_user: str = "alice"
    pdf_storage_dir: str = "./data/exports"
    cors_origins: str = "http://localhost:5173"
    migration_database_url: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

if settings.auth_mode == "local" and settings.app_env not in {"local", "test"}:
    raise RuntimeError("AUTH_MODE=local is allowed only when APP_ENV is local or test")
