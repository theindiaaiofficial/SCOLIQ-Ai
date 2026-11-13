from __future__ import annotations

import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import DomainError, domain_error_handler, http_error_handler, validation_error_handler
from app.core.middleware import InProcessRateLimiter, RequestContextMiddleware, rate_limit_middleware
from app.database import build_engine, build_session_factory
from app.face.provider import FakeFaceProvider, ManualOnlyProvider, ProviderUnavailable
from app.face.opencv_provider import OpenCVYuNetSFaceProvider
from app.face.mobilefacenet_provider import YuNetMobileFaceNetProvider
from app.face.diagnostics import configure_face_diagnostics, log_face_event

logger = logging.getLogger("smartattend")


class UnavailableFaceProvider:
    provider_name = "unavailable"
    model_name = "unavailable"
    model_version = "unavailable"

    def create_embedding(self, image_bytes: bytes):
        raise ProviderUnavailable("Configured face model files are not available. Follow the FACE_MODEL_REVIEW instructions.")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_face_diagnostics(settings.face_diagnostics_enabled)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = None
        app.state.session_factory = None
        if settings.database_url:
            engine = build_engine(settings.database_url)
            app.state.engine = engine
            app.state.session_factory = build_session_factory(engine)
        if settings.face_provider == "manual":
            app.state.face_provider = ManualOnlyProvider()
        elif settings.face_provider == "fake":
            if settings.app_env not in {"development", "test"}:
                raise RuntimeError("Fake face provider is forbidden outside development/test")
            app.state.face_provider = FakeFaceProvider()
        elif settings.face_provider == "opencv_sface":
            try:
                app.state.face_provider = OpenCVYuNetSFaceProvider(
                    settings.face_detector_model_path,
                    settings.face_recognizer_model_path,
                    settings.face_model_name,
                    settings.face_model_version,
                )
            except ProviderUnavailable as exc:
                logger.error("face_provider_unavailable reason=%s", str(exc))
                app.state.face_provider = UnavailableFaceProvider()
        elif settings.face_provider == "mobilefacenet":
            try:
                app.state.face_provider = YuNetMobileFaceNetProvider(
                    settings.face_detector_model_path,
                    settings.face_mobilefacenet_model_path,
                    settings.face_mobilefacenet_model_name,
                    settings.face_mobilefacenet_model_version,
                    metadata_path=settings.face_mobilefacenet_metadata_path,
                    external_data_path=settings.face_mobilefacenet_external_data_path,
                    input_size=settings.face_mobilefacenet_input_size,
                    embedding_size=settings.face_mobilefacenet_embedding_size,
                    input_name_1=settings.face_mobilefacenet_input_name_1,
                    input_name_2=settings.face_mobilefacenet_input_name_2,
                    output_name=settings.face_mobilefacenet_output_name,
                    score_threshold=settings.face_detector_score_threshold,
                    nms_threshold=settings.face_detector_nms_threshold,
                    min_face_size=settings.face_min_face_size,
                )
                log_face_event(
                    "provider.startup_ready",
                    provider="qualcomm-yunet-mobilefacenet",
                    detector_score_threshold=settings.face_detector_score_threshold,
                    detector_nms_threshold=settings.face_detector_nms_threshold,
                    min_face_size_px=settings.face_min_face_size,
                    match_threshold=settings.face_match_threshold,
                    ambiguity_margin=settings.face_ambiguity_margin,
                )
            except ProviderUnavailable as exc:
                log_face_event(
                    "provider.startup_unavailable",
                    provider="qualcomm-yunet-mobilefacenet",
                    exception_type=type(exc).__name__,
                    reason=str(exc),
                )
                logger.error("face_provider_unavailable reason=%s", str(exc))
                app.state.face_provider = UnavailableFaceProvider()
        app.state.settings = settings
        app.state.rate_limiter = InProcessRateLimiter(settings.rate_limit_requests, settings.rate_limit_window_seconds)
        yield
        if app.state.engine is not None:
            app.state.engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="School-isolated attendance API and web platform.",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        docs_url=f"{settings.api_v1_prefix}/docs",
        redoc_url=f"{settings.api_v1_prefix}/redoc",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID", "X-Class-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    app.middleware("http")(rate_limit_middleware)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/health/live", tags=["Operations"])
    def live():
        return {"status": "alive"}

    @app.get("/health/ready", tags=["Operations"])
    def ready(request: Request):
        factory = getattr(request.app.state, "session_factory", None)
        if factory is None:
            raise HTTPException(status_code=503, detail={"code": "DATABASE_UNAVAILABLE", "message": "Database is not configured."})
        try:
            with factory() as db:
                db.execute(text("SELECT 1"))
        except Exception as exc:
            logger.warning("readiness_database_check_failed error_type=%s", type(exc).__name__)
            raise HTTPException(status_code=503, detail={"code": "DATABASE_UNAVAILABLE", "message": "Database readiness check failed."}) from exc
        return {"status": "ready", "database": "reachable", "face_provider": request.app.state.face_provider.provider_name}

    # Serve the compiled, same-origin web application when the frontend build
    # is present. The Vite development server proxies /api to this service.
    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if (frontend_dist / "index.html").is_file():
        assets_dir = frontend_dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

        @app.get("/", include_in_schema=False)
        def frontend_root():
            return FileResponse(frontend_dist / "index.html")

        @app.get("/{frontend_path:path}", include_in_schema=False)
        def frontend_routes(frontend_path: str):
            if frontend_path.startswith(("api/", "health/")) or frontend_path in {"docs", "redoc"}:
                raise HTTPException(status_code=404, detail="Not found")
            candidate = (frontend_dist / frontend_path).resolve()
            if frontend_dist.resolve() in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(frontend_dist / "index.html")

    return app


app = create_app()
