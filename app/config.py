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
    paddle_environment: str = "sandbox"
    paddle_client_token: str | None = None
    paddle_api_key: str | None = None
    paddle_webhook_secret: str | None = None
    paddle_creator_monthly_price_id: str | None = None
    paddle_creator_annual_price_id: str | None = None
    paddle_pro_monthly_price_id: str | None = None
    paddle_pro_annual_price_id: str | None = None
    paddle_studio_monthly_price_id: str | None = None
    paddle_studio_annual_price_id: str | None = None

    @property
    def paddle_api_base_url(self) -> str:
        return (
            "https://sandbox-api.paddle.com"
            if self.paddle_environment == "sandbox"
            else "https://api.paddle.com"
        )

    @property
    def paddle_plans(self) -> dict[str, dict]:
        return {
            "creator_monthly": {
                "name": "Creator",
                "interval": "month",
                "credits": 100_000,
                "price_id": self.paddle_creator_monthly_price_id,
            },
            "creator_annual": {
                "name": "Creator",
                "interval": "year",
                "credits": 1_200_000,
                "price_id": self.paddle_creator_annual_price_id,
            },
            "pro_monthly": {
                "name": "Pro",
                "interval": "month",
                "credits": 400_000,
                "price_id": self.paddle_pro_monthly_price_id,
            },
            "pro_annual": {
                "name": "Pro",
                "interval": "year",
                "credits": 4_800_000,
                "price_id": self.paddle_pro_annual_price_id,
            },
            "studio_monthly": {
                "name": "Studio",
                "interval": "month",
                "credits": 1_500_000,
                "price_id": self.paddle_studio_monthly_price_id,
            },
            "studio_annual": {
                "name": "Studio",
                "interval": "year",
                "credits": 18_000_000,
                "price_id": self.paddle_studio_annual_price_id,
            },
        }

    @property
    def paddle_enabled(self) -> bool:
        return bool(
            self.paddle_client_token
            and self.paddle_webhook_secret
            and any(plan["price_id"] for plan in self.paddle_plans.values())
        )

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def saved_voices_dir(self) -> Path:
        return self.data_dir / "saved-voices"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'voiceforge.db').as_posix()}"


settings = Settings()
settings.jobs_dir.mkdir(parents=True, exist_ok=True)
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
settings.saved_voices_dir.mkdir(parents=True, exist_ok=True)

