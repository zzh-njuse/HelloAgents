import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from learn_platform_api import __version__
from learn_platform_api.observability import RequestIdMiddleware, configure_logging
from learn_platform_api.routers import agent_runs, courses, documents, health, learning, mcp, practice, provider_calls, quality_cost, system, tutor, workspaces
from learn_platform_api.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()

    app = FastAPI(title=settings.app_name, version=__version__)
    app.add_middleware(RequestIdMiddleware, header_name=settings.request_id_header)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(system.router)
    app.include_router(workspaces.router)
    app.include_router(documents.router)
    app.include_router(courses.router)
    app.include_router(agent_runs.router)
    app.include_router(tutor.router)
    app.include_router(practice.router)
    app.include_router(learning.router)
    app.include_router(mcp.router)
    app.include_router(provider_calls.router)
    app.include_router(quality_cost.router)

    logging.getLogger("learn_platform_api").info(
        "application_started",
        extra={"environment": settings.environment},
    )
    return app


app = create_app()
