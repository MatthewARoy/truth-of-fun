from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.discovery import router as discovery_router
from app.api.health import router as health_router
from app.api.internal_secrets import router as internal_secrets_router
from app.api.social import router as social_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(discovery_router)
app.include_router(social_router)
app.include_router(internal_secrets_router)
