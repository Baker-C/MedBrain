"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from config import load_settings


def create_app() -> FastAPI:
    app = FastAPI(title="MedBrain")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[load_settings().frontend_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app
