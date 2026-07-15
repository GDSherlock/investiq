"""POST /models/upload — triggers ModelIngestAgent; returns model_id and health report.
   POST /models/{id}/parse — re-parse model.
"""

import os
import uuid
import shutil
from typing import Any

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional

from ..database import get_db
from ..models import FinancialModel, Investment, ModelAssumption, AuditLog, User
from ..schemas import ModelUploadResponse, ModelParseResponse, WorkbookValidationResponse
from ..auth import get_current_user
from ..model_extraction_service import ModelExtractionPersistenceService
from ..model_extraction_types import ModelExtractionPersistenceError, WorkbookTooLargeError
from ..vector_service import vectorize_and_store
from ..workbook_validation import (
    AzureConfigurationError,
    AzureResponsesError,
    InvalidWorkbookError,
    WorkbookValidationError,
    run_workbook_validation,
)

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))

from libs.tools.excel_parser import ExcelParser
from libs.tools.assumption_mapper import AssumptionMapper

router = APIRouter()

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")


def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


@router.post(
    "/models/upload",
    response_model=WorkbookValidationResponse,
    summary="Experimental workbook-agent validation endpoint",
    description=(
        "Synchronous Azure Responses API workbook exploration and deterministic "
        "validation endpoint for benchmark testing. Supports .xlsx only."
    ),
)
async def upload_model(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Run and durably persist the synchronous workbook-agent validation flow."""
    filename = file.filename or ""
    if not filename.lower().endswith(".xlsx"):
        raise _api_error(
            415,
            "UNSUPPORTED_WORKBOOK_FORMAT",
            "Only .xlsx is supported; legacy .xls is not reliably readable by this toolchain.",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise _api_error(400, "EMPTY_FILE", "Uploaded workbook is empty.")

    try:
        service = ModelExtractionPersistenceService(
            session=db,
            validation_runner=run_workbook_validation,
        )
        return service.process_upload(file_bytes, filename)
    except InvalidWorkbookError:
        raise _api_error(
            422,
            "INVALID_XLSX",
            "The upload is not a readable OOXML workbook.",
        )
    except AzureConfigurationError:
        raise _api_error(
            503,
            "AZURE_CONFIGURATION_ERROR",
            "Required Azure OpenAI configuration is missing.",
        )
    except AzureResponsesError:
        raise _api_error(
            502,
            "AZURE_RESPONSES_ERROR",
            "Azure Responses API execution failed.",
        )
    except WorkbookValidationError:
        raise _api_error(
            500,
            "WORKBOOK_VALIDATION_ERROR",
            "Local workbook-agent validation failed.",
        )
    except WorkbookTooLargeError:
        raise _api_error(
            413,
            "WORKBOOK_TOO_LARGE",
            "The uploaded workbook exceeds the configured size limit.",
        )
    except ModelExtractionPersistenceError:
        raise _api_error(
            500,
            "MODEL_EXTRACTION_PERSISTENCE_ERROR",
            "Model Extraction persistence failed.",
        )


async def _legacy_upload_model_for_rollback(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """Unregistered production upload implementation retained for easy rollback."""
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only .xlsx/.xls files accepted")

    # Read file bytes
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Save to disk
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{file_id}_{file.filename}")
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    # Parse with ExcelParser
    parser = ExcelParser(file_bytes=file_bytes)
    parsed_data = parser.parse_all()
    health = parser.health_check()

    # Create investment (default)
    cover = parsed_data.get("cover", {})
    investment = Investment(
        id=str(uuid.uuid4()),
        name=cover.get("Project", cover.get("project", file.filename)),
        asset_class="Infrastructure",
        status="active",
    )
    db.add(investment)

    # Create financial model record
    user_id = str(current_user.id) if current_user else None
    model = FinancialModel(
        id=file_id,
        investment_id=investment.id,
        file_path=file_path,
        original_filename=file.filename,
        parsed_json=parsed_data,
        health_score=health["health_score"],
        uploaded_by=user_id,
    )
    db.add(model)

    # Store assumptions
    assumptions = parsed_data.get("assumptions", [])
    mapped = AssumptionMapper.map_all(assumptions)
    for a in mapped:
        db.add(ModelAssumption(
            model_id=file_id,
            key=a.get("name", ""),
            value=str(a.get("value", "")),
            unit=a.get("unit"),
            source=a.get("source"),
            is_hardcoded=not bool(a.get("source")),
        ))

    # Audit log
    db.add(AuditLog(
        action="model_upload",
        entity_type="FinancialModel",
        entity_id=file_id,
        user_id=user_id,
        payload={"filename": file.filename, "health_score": health["health_score"], "uploaded_by": user_id},
    ))

    db.commit()

    # Vectorize the parsed data and store in pgvector
    try:
        chunk_count = vectorize_and_store(db, file_id, parsed_data, file.filename, user_id)
    except Exception as e:
        print(f"[upload] Vectorization warning (non-fatal): {e}")
        chunk_count = 0

    return ModelUploadResponse(
        model_id=file_id,
        investment_id=str(investment.id),
        health_report=health,
        parsed_sheets=parsed_data.get("sheets", []),
        assumptions_count=len(assumptions),
    )


@router.post("/models/{model_id}/parse", response_model=ModelParseResponse)
async def reparse_model(
    model_id: str,
    db: Session = Depends(get_db),
):
    """Re-parse an existing model."""
    model = db.query(FinancialModel).filter(FinancialModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    if not model.file_path or not os.path.exists(model.file_path):
        raise HTTPException(status_code=404, detail="Model file not found on disk")

    parser = ExcelParser(file_path=model.file_path)
    parsed_data = parser.parse_all()
    health = parser.health_check()

    model.parsed_json = parsed_data
    model.health_score = health["health_score"]

    db.add(AuditLog(
        action="model_reparse",
        entity_type="FinancialModel",
        entity_id=model_id,
        payload={"health_score": health["health_score"]},
    ))
    db.commit()

    return ModelParseResponse(
        model_id=model_id,
        parsed_json=parsed_data,
        health_score=health["health_score"],
    )


@router.get("/models/{model_id}")
async def get_model(
    model_id: str,
    db: Session = Depends(get_db),
):
    """Get model details including parsed data."""
    model = db.query(FinancialModel).filter(FinancialModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    return JSONResponse(
        content={
            "id": str(model.id),
            "investment_id": str(model.investment_id) if model.investment_id else None,
            "original_filename": model.original_filename,
            "parsed_json": model.parsed_json,
            "health_score": model.health_score,
            "schema_version": model.schema_version,
            "uploaded_at": str(model.uploaded_at) if model.uploaded_at else None,
        },
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@router.get("/models/{model_id}/assumptions")
async def get_model_assumptions(
    model_id: str,
    category: str | None = None,
    db: Session = Depends(get_db),
):
    """Get model assumptions, optionally filtered by category."""
    model = db.query(FinancialModel).filter(FinancialModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    assumptions = model.parsed_json.get("assumptions", []) if model.parsed_json else []

    if category:
        assumptions = AssumptionMapper.get_by_category(assumptions, category.upper())
    else:
        assumptions = AssumptionMapper.map_all(assumptions)

    return {"model_id": model_id, "assumptions": assumptions}
