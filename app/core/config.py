from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite+aiosqlite:///./webhook.db"
    log_level: str = "INFO"
    env: str = "development"
    rate_limit_requests: int = 100
    rate_limit_window_seconds: float = 60.0
    # Optional webhook URL (Slack incoming webhook, etc.) to notify on success
    notification_webhook_url: str | None = None
    # Stripe webhook signing secret (whsec_...) for signature verification
    stripe_webhook_secret: str | None = None
