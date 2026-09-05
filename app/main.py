from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.learning_path import router as learning_path_router
from app.api.v1.routes.ask import router as ask_router

# Hermes Agent route is prepared as baseline stub for upcoming sprint
try:
    from app.api.v1.routes.hermes import router as hermes_router
except (ImportError, Exception):
    hermes_router = None


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="Ambis.in Backend API - Learning Path & Ask Mode",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, prefix=settings.api_v1_prefix)
    app.include_router(learning_path_router, prefix=settings.api_v1_prefix)
    app.include_router(ask_router, prefix=settings.api_v1_prefix)
    if hermes_router:
        app.include_router(hermes_router, prefix=settings.api_v1_prefix)

    @app.get("/")
    async def root():
        return {"message": "ambis.in API", "docs": "/docs"}

    return app


app = create_app()
