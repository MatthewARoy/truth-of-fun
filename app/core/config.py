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

    log_level: str = Field(
        default="INFO",
        description="Root log level for the API and worker (DEBUG/INFO/WARNING/ERROR).",
    )
    log_format: str = Field(
        default="text",
        description=(
            "Log output format: 'text' for local terminals, 'json' for one "
            "JSON object per line (docker/aggregators). See docs/operations.md."
        ),
    )
    log_slow_request_ms: int = Field(
        default=1000,
        description=(
            "Requests slower than this are logged at WARNING so latency "
            "regressions surface without reading every access line."
        ),
    )
    expose_error_detail: bool | None = Field(
        default=None,
        description=(
            "Whether publicly reachable health endpoints include exception "
            "messages as well as exception types. Defaults to true only in "
            "development: messages are where DSNs, hosts, and API keys leak. "
            "Full detail is always written to the logs regardless."
        ),
    )

    @property
    def error_detail_is_public(self) -> bool:
        """Resolve ``expose_error_detail``, defaulting by environment."""
        if self.expose_error_detail is not None:
            return self.expose_error_detail
        return self.app_env == "development"

    # Proxy configuration for scrapers (IP rotation when needed)
    proxy_url: str | None = Field(
        default=None,
        description="Single proxy URL, e.g. http://user:pass@host:port",
    )
    proxy_rotation: list[str] | None = Field(
        default=None,
        description="List of proxy URLs for rotation; used when proxy_rotation is set",
    )
    ops_token: str = Field(
        default="",
        description=(
            "Shared secret gating the operator health endpoints "
            "(/health/sources, /health/summary) and the /admin pages that read "
            "them. Sent as the X-Ops-Token header. Unset in development leaves "
            "them open; unset anywhere else locks them shut."
        ),
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
        default=["RS256"],
        description=(
            "Allowed asymmetric JWT algorithms for OIDC/JWKS internal bot tokens. "
            "HS256 is selected only by configuring AAIM_JWT_SHARED_SECRET."
        ),
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
        ge=1,
        description="JWT expiration in minutes (default 7 days)",
    )
    max_request_body_bytes: int = Field(
        default=1_000_000,
        ge=0,
        description="Maximum inbound HTTP request body size. 0 disables the guard.",
    )

    rate_limit_llm_per_hour: int = Field(
        default=30,
        ge=0,
        description=(
            "Per-client hourly cap on endpoints that call the LLM per request "
            "(concierge itinerary builds, onboarding tag extraction). 0 disables."
        ),
    )
    rate_limit_share_per_hour: int = Field(
        default=60,
        ge=0,
        description=(
            "Per-client hourly cap on itinerary share creation (each share "
            "persists a public snapshot row). 0 disables."
        ),
    )
    rate_limit_auth_per_quarter_hour: int = Field(
        default=20,
        ge=0,
        description=(
            "Per-client cap on login/register attempts per 15 minutes "
            "(credential-stuffing and signup-abuse guard). 0 disables."
        ),
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
    if settings.app_env != "development" and (
        settings.jwt_secret_key == DEV_JWT_SECRET
        or len(settings.jwt_secret_key.encode("utf-8")) < 32
    ):
        raise RuntimeError(
            "JWT_SECRET_KEY must be at least 32 bytes and must not use the development default "
            "when APP_ENV is not 'development'. "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    if (
        settings.app_env != "development"
        and settings.cors_allow_credentials
        and "*" in settings.cors_allowed_origins
    ):
        raise RuntimeError(
            "CORS_ALLOWED_ORIGINS cannot contain '*' when credentials are enabled in production."
        )
    if (
        settings.app_env != "development"
        and settings.ops_token
        and len(settings.ops_token.encode("utf-8")) < 32
    ):
        raise RuntimeError(
            "OPS_TOKEN must be at least 32 bytes when APP_ENV is not 'development'. "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    if settings.aaim_enabled and settings.app_env != "development":
        if not settings.aaim_oidc_issuer or not settings.aaim_oidc_audience:
            raise RuntimeError(
                "AAIM_OIDC_ISSUER and AAIM_OIDC_AUDIENCE are required when AAIM is enabled "
                "outside development."
            )
        if not settings.aaim_jwt_shared_secret and not settings.aaim_oidc_jwks_url:
            raise RuntimeError(
                "Configure AAIM_OIDC_JWKS_URL or AAIM_JWT_SHARED_SECRET when AAIM is enabled."
            )
        if settings.aaim_jwt_shared_secret and len(
            settings.aaim_jwt_shared_secret.encode("utf-8")
        ) < 32:
            raise RuntimeError("AAIM_JWT_SHARED_SECRET must be at least 32 bytes.")
    return settings
