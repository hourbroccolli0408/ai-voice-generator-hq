from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VOICEFORGE_", env_file=".env", extra="ignore")

    app_name: str = "AI Voice Generator HQ"
    environment: str = "development"
    data_dir: Path = Path("data")
    device: str = "auto"
    engine: str = "chatterbox"
    worker_mode: str = "local"
    runpod_endpoint_id: str | None = None
    runpod_api_key: str | None = None
    runpod_timeout_seconds: int = 900
    max_text_chars: int = 5000
    max_upload_mb: int = 30
    workers: int = 1
    database_url: str | None = None
    starter_credits: int = 5000
    auth_mode: str = "disabled"
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_jwt_secret: str | None = None
    storage_backend: str = "local"
    r2_endpoint_url: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str | None = None
    r2_public_url: str | None = None

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'voiceforge.db').as_posix()}"


settings = Settings()
settings.jobs_dir.mkdir(parents=True, exist_ok=True)
settings.uploads_dir.mkdir(parents=True, exist_ok=True)

