"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import OpenAIError

from api.routes import router
from api.state import build_clients
from config import load_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Read settings and build the shared clients once, before the first request."""
    app.state.clients = build_clients(load_settings())
    yield


def database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """A database failure before a stream starts becomes a typed 503, not a stack trace."""
    return JSONResponse(status_code=503, content={"detail": "database unavailable"})


def model_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """An OpenAI failure before a stream starts becomes a typed 502, not a stack trace.

    Mid-stream failures never reach here — the chat layer turns those into an `error`
    event on the already-open stream.
    """
    return JSONResponse(status_code=502, content={"detail": "language model unavailable"})


def create_app() -> FastAPI:
    app = FastAPI(title="MedBrain", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[load_settings().frontend_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(psycopg.Error, database_unavailable)
    app.add_exception_handler(OpenAIError, model_unavailable)
    app.include_router(router)
    return app
