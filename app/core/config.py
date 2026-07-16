import random
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "truth-of-fun"
    app_env: str = "development"
    cors_allowed_origins: list[str] = Field(
        default=["http://127.0.0.1:3000", "http://localhost:3000"],
        description="Allowed browser origins for web clients.",
    )
    cors_allow_credentials: bool = Field(
        default=True,
        description="Whether cross-origin requests can include credentials.",
    )
    database_url: str = Field(
        default="postgresql+psycopg2://postgres:postgres@127.0.0.1:5433/truth_of_fun"
    )
    ticketmaster_api_key: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = Field(
        default="claude-haiku-4-5",
        description=(
            "Claude model for all LLM calls (vibe tagging, intent parsing, Reddit "
            "extraction). Use the dateless alias so snapshot rotations can't 404 us."
        ),
    )
    # Reddit OAuth ("script" app). Anonymous JSON access is now blocked (403),
    # so live Reddit ingestion requires a registered app's client id + secret.
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = Field(
        default="truth-of-fun/0.1 (event discovery; +https://github.com/MatthewARoy/truth-of-fun)",
        description="Reddit requires a unique, descriptive User-Agent on every request.",
    )
    worker_interval_seconds: int = Field(
        default=6 * 60 * 60,
        description="Ingestion worker polling interval in seconds",
    )

    # Proxy configuration for scrapers (IP rotation when needed)
    proxy_url: str | None = Field(
        default=None,
        description="Single proxy URL, e.g. http://user:pass@host:port",
    )
    proxy_rotation: list[str] | None = Field(
        default=None,
        description="List of proxy URLs for rotation; used when proxy_rotation is set",
    )
    aaim_enabled: bool = Field(
        default=False,
        description="Enable AAIM internal auth and secrets features.",
    )
    aaim_fallback_to_env: bool = Field(
        default=True,
        description="Allow env-based secret fallback when Redis store has no keys.",
    )
    aaim_oidc_issuer: str | None = Field(
        default=None,
        description="Expected JWT issuer for internal bot authentication.",
    )
    aaim_oidc_audience: str | None = Field(
        default=None,
        description="Expected JWT audience for internal bot authentication.",
    )
    aaim_oidc_jwks_url: str | None = Field(
        default=None,
        description="JWKS URL for validating internal bot JWTs.",
    )
    aaim_jwt_shared_secret: str | None = Field(
        default=None,
        description="Optional HS256 secret for local/dev token verification.",
    )
    aaim_jwt_algorithms: list[str] = Field(
        default=["RS256", "HS256"],
        description="Allowed JWT signing algorithms for internal bot tokens.",
    )
    jwt_secret_key: str = Field(
        default="dev-only-insecure-secret-do-not-use-in-production",
        description=(
            "Secret key for signing end-user JWTs. MUST be overridden via the "
            "JWT_SECRET_KEY env var in any non-development environment. "
            "Generate with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        ),
    )
    jwt_expire_minutes: int = Field(
        default=60 * 24 * 7,
        description="JWT expiration in minutes (default 7 days)",
    )

    alert_webhook_url: str | None = Field(
        default=None,
        description="Webhook URL (Slack/Discord) for operational alerts. POST with JSON body.",
    )

    # IMAP mailbox for newsletter ingestion (Eddie's List). Leave unset to disable.
    imap_host: str | None = Field(
        default=None,
        description="IMAP server hostname for newsletter ingestion.",
    )
    imap_port: int = Field(
        default=993,
        description="IMAP server port (SSL).",
    )
    imap_user: str | None = Field(
        default=None,
        description="IMAP mailbox username.",
    )
    imap_password: str | None = Field(
        default=None,
        description="IMAP mailbox password or app password.",
    )
    imap_mailbox: str = Field(
        default="INBOX",
        description="IMAP folder to read newsletters from.",
    )
    eddies_list_allowed_senders: list[str] = Field(
        default=["eddieslist.com"],
        description="Sender address/domain allowlist for Eddie's List ingestion trust.",
    )

    redis_url: str = Field(
        default="redis://127.0.0.1:6379/0",
        description="Redis URL used for AAIM secrets store.",
    )
    aaim_redis_prefix: str = Field(
        default="aaim",
        description="Redis key prefix used by AAIM components.",
    )
    aaim_ticketmaster_quota_limit: int = Field(
        default=10000,
        description="Default quota threshold for Ticketmaster keys in AAIM store.",
    )
    aaim_quota_window_hours: int = Field(
        default=24,
        description=(
            "Hours after which an exhausted AAIM key auto-reactivates (its quota "
            "window rolls over). 0 disables automatic reset."
        ),
    )

    def get_proxy_for_scraper(self) -> str | None:
        """Return proxy URL for scraper. Supports rotation via proxy_rotation list."""
        if self.proxy_rotation and len(self.proxy_rotation) > 0:
            return random.choice(self.proxy_rotation)
        return self.proxy_url

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


DEV_JWT_SECRET = "dev-only-insecure-secret-do-not-use-in-production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    if settings.app_env != "development" and settings.jwt_secret_key == DEV_JWT_SECRET:
        raise RuntimeError(
            "JWT_SECRET_KEY must be set when APP_ENV is not 'development'. "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    return settings
