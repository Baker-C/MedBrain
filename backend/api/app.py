"""FastAPI application factory."""

from fastapi import FastAPI

from api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="MedBrain")
    app.include_router(router)
    return app
