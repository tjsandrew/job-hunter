from typing import Literal
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
    model_backend: Literal["heuristic", "fake", "ollama", "hosted", "bedrock"] = "heuristic"
    ollama_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.2"
    llm_timeout_seconds: int = 600
    llm_base_url: str = ""   # backend "hosted": e.g. https://api.groq.com/openai/v1
    llm_api_key: str = ""    # backend "hosted": from the environment or a secret store, never committed
    llm_model: str = ""
    llm_reasoning_effort: str = ""   # backend "hosted": "none" for reasoning models such as the SoCLaaS gemma/qwen ones
    llm_worker: Literal["inline", "s3"] = "inline"   # "inline" calls the model in this process; "s3" hands the work to the LLM worker Lambda
    storage_backend: Literal["local", "s3"] = "local"
    document_bucket: str = ""
    database_auth: Literal["password", "iam"] = "password"
    database_host: str = ""
    database_name: str = "jobhunter"
    database_username: str = ""
    db_pool_size: int = 3
    cognito_issuer: str = ""
    cognito_client_id: str = ""
    api_scope: str = "jobhunter/use"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

if settings.auth_mode == "local" and settings.app_env not in {"local", "test"}:
    raise RuntimeError("AUTH_MODE=local is allowed only when APP_ENV is local or test")
if settings.auth_mode not in {"local", "cognito"}:
    raise RuntimeError("Unknown AUTH_MODE")
if settings.auth_mode == "cognito" and not (settings.cognito_issuer and settings.cognito_client_id):
    raise RuntimeError("Cognito issuer and client ID are required")
if settings.storage_backend == "s3" and not settings.document_bucket:
    raise RuntimeError("DOCUMENT_BUCKET is required for S3 storage")
if settings.llm_worker == "s3" and not settings.document_bucket:
    raise RuntimeError("DOCUMENT_BUCKET is required when LLM_WORKER=s3")
if settings.database_auth == "iam" and not (settings.database_host and settings.database_username):
    raise RuntimeError("IAM database authentication requires host and username")
if settings.app_env == "aws" and not (settings.auth_mode == "cognito" and settings.storage_backend == "s3" and settings.database_host and settings.database_username):
    raise RuntimeError("AWS requires Cognito, S3 and explicit database host and username")
