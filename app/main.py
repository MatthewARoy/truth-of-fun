import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.discovery import router as discovery_router
from app.api.health import router as health_router
from app.api.internal_secrets import router as internal_secrets_router
from app.api.middleware import RequestContextMiddleware
from app.api.social import router as social_router
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()

# Configure logging before anything else so import-time and startup messages
# use the configured format rather than Python's default lastResort handler.
configure_logging()
logger = logging.getLogger(__name__)

API_VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Record what the process booted with, so logs open with its configuration.

    Only booleans for credentials — never the key material itself.
    """
    logger.info(
        "API starting: env=%s version=%s log_format=%s",
        settings.app_env,
        API_VERSION,
        settings.log_format,
        extra={
            "app_env": settings.app_env,
            "api_version": API_VERSION,
            "anthropic_configured": bool(settings.anthropic_api_key),
            "ticketmaster_configured": bool(settings.ticketmaster_api_key),
        },
    )
    yield
    logger.info("API shutting down.")


app = FastAPI(
    title=settings.app_name,
    version=API_VERSION,
    lifespan=lifespan,
    description=(
        "Truth of Fun event discovery API. The v1 contract is documented in "
        "docs/api-contract-v1.md; changes are additive. This OpenAPI schema is "
        "the source of truth for the TypeScript client (packages/api-client) "
        "and the MCP server (packages/mcp-server)."
    ),
)

# Order matters: the request-context middleware is added last so it runs
# outermost, and therefore sees the final status code of every request
# (including CORS preflights and anything a later middleware rejects).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    # Browsers hide every response header except a short safelist unless it is
    # named here. Without this the web client reads null from X-Total-Count
    # even though the server sent it, and a user reporting a bug can't see the
    # request id to quote.
    expose_headers=["X-Total-Count", "X-Request-ID"],
)
app.add_middleware(RequestContextMiddleware)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(discovery_router)
app.include_router(social_router)
app.include_router(internal_secrets_router)
