import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from starlette.responses import Response

from relayqueue.api.routes.jobs import router as jobs_router
from relayqueue.api.routes.workers import router as workers_router
from relayqueue.core.logging_config import (
    configure_logging,
    request_id_context,
)
from relayqueue.database.connection import engine

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="RelayQueue API",
    description=("A fault-tolerant distributed job scheduling and execution platform."),
    version="0.1.0",
)


@app.middleware("http")
async def request_logging_middleware(
    request: Request,
    call_next,
):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request_id = request_id[:128]

    token = request_id_context.set(request_id)

    try:
        response = await call_next(request)

        response.headers["X-Request-ID"] = request_id

        logger.info(
            "HTTP request completed | method=%s | path=%s | status=%s",
            request.method,
            request.url.path,
            response.status_code,
        )

        return response

    except Exception:
        logger.exception(
            "HTTP request failed | method=%s | path=%s",
            request.method,
            request.url.path,
        )
        raise

    finally:
        request_id_context.reset(token)


app.include_router(jobs_router)
app.include_router(workers_router)


@app.get("/health", tags=["System"])
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "database": "connected",
        }

    except Exception:
        logger.exception("Database health check failed")

        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "database": "unavailable",
            },
        )


@app.get("/metrics", tags=["Monitoring"])
def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
