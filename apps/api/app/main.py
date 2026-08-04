"""InvestIQ Backend API — FastAPI application."""

import sys
import os
import uuid
import json
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()


class UUIDEncoder(json.JSONEncoder):
    """JSON encoder that handles UUID and datetime objects."""
    def default(self, obj):
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class UUIDJSONResponse(JSONResponse):
    """JSONResponse that serializes UUID objects."""
    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            cls=UUIDEncoder,
            separators=(",", ":"),
        ).encode("utf-8")

# Add libs to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from .database import engine, Base
from . import model_extraction_models  # noqa: F401
from . import analysis_models  # noqa: F401
from . import report_chat_models  # noqa: F401
from .calculation_rules import models as calculation_rule_models  # noqa: F401
from .calculation_rules import phase2_models as calculation_engine_models  # noqa: F401
from .routers import (
    alerts,
    assistant,
    audit,
    calculations,
    canonical_reports,
    debt_analysis,
    market_data,
    models,
    report_chat,
    reports,
    scenarios,
)
from .routers import auth as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # SQLite remains self-bootstrapping for local development and tests.
    # Deployed PostgreSQL schemas are advanced explicitly through Alembic.
    auto_create_schema = engine.url.get_backend_name() == "sqlite" or os.getenv(
        "AUTO_CREATE_SCHEMA", "false"
    ).lower() == "true"
    if auto_create_schema:
        Base.metadata.create_all(bind=engine)
    yield
    # Shutdown


app = FastAPI(
    title="InvestIQ API",
    description="Investment Capital Decision Intelligence API",
    version="1.0.0",
    lifespan=lifespan,
    default_response_class=UUIDJSONResponse,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth_router.router, prefix="/api/v1", tags=["Auth"])
app.include_router(models.router, prefix="/api/v1", tags=["Models"])
app.include_router(calculations.router, prefix="/api/v1")
app.include_router(canonical_reports.router, prefix="/api/v1")
app.include_router(report_chat.router, prefix="/api/v1")
app.include_router(scenarios.router, prefix="/api/v1", tags=["Scenarios"])
app.include_router(debt_analysis.router, prefix="/api/v1", tags=["Debt Analysis"])
app.include_router(reports.router, prefix="/api/v1", tags=["Reports"])
app.include_router(alerts.router, prefix="/api/v1", tags=["Alerts"])
app.include_router(audit.router, prefix="/api/v1", tags=["Audit"])
app.include_router(market_data.router, prefix="/api/v1", tags=["Market Data"])
app.include_router(assistant.router, prefix="/api/v1", tags=["Assistant"])


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "investiq-api"}
