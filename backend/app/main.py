from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.errors import AppError, app_error_handler, envelope, unhandled_error_handler
from app.core.logging import configure_logging, new_trace_id
from app import models_registry  # noqa: F401  触发全部 ORM 模型注册
from app.modules.asset.router import router as connections_router
from app.modules.asset.router import secrets_router
from app.modules.bench.router import router as bench_router
from app.modules.exec.router import router as execution_router
from app.modules.harness.router import router as harness_router
from app.modules.iam.router import auth_router, projects_router
from app.modules.meta.router import router as metadata_router
from app.modules.pipe.router import router as pipeline_router
from app.modules.studio.router import router as studio_router


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or new_trace_id()
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ETL-Agent 控制面", version="0.2.0", lifespan=lifespan)

    app.add_middleware(TraceIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=envelope(
                "SYS_VALIDATION_ERROR",
                "请求参数不合法",
                {"errors": exc.errors()},
                getattr(request.state, "trace_id", None),
            ),
        )

    api_prefix = settings.api_prefix
    for router in (
        auth_router,
        projects_router,
        connections_router,
        secrets_router,
        metadata_router,
        studio_router,
        pipeline_router,
        harness_router,
        execution_router,
        bench_router,
    ):
        app.include_router(router, prefix=api_prefix)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
