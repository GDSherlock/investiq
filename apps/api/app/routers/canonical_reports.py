"""HTTP contract for canonical asynchronous report artifacts."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..analysis_presentation_service import AnalysisPresentationService
from ..calculation_integration_service import (
    CalculationIntegrationError,
    CalculationIntegrationService,
)
from ..canonical_report_service import CanonicalReportService
from ..database import get_db
from ..model_extraction_read_service import ModelExtractionReadService
from ..monte_carlo_service import MonteCarloService
from ..schemas import (
    CanonicalReportCreateRequest,
    CanonicalReportHistoryResponse,
    CanonicalReportResponse,
)
from ..workbook_storage import DatabaseWorkbookStorage


router = APIRouter(tags=["Canonical Reports"])


def get_canonical_report_service(
    session: Session = Depends(get_db),
) -> CanonicalReportService:
    calculation_service = CalculationIntegrationService(
        session,
        ModelExtractionReadService(
            session,
            DatabaseWorkbookStorage(session),
        ),
    )
    return CanonicalReportService(
        session,
        calculation_service,
        AnalysisPresentationService(session, calculation_service),
        MonteCarloService(session, calculation_service),
    )


def _translate_error(error: CalculationIntegrationError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail=error.detail(),
    ) from error


@router.post(
    "/models/{model_version_id}/reports",
    response_model=CanonicalReportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_canonical_report(
    model_version_id: UUID,
    request: CanonicalReportCreateRequest,
    service: CanonicalReportService = Depends(
        get_canonical_report_service
    ),
) -> CanonicalReportResponse:
    try:
        return service.create_run(str(model_version_id), request)
    except CalculationIntegrationError as error:
        _translate_error(error)


@router.get(
    "/report-runs/{report_id}",
    response_model=CanonicalReportResponse,
)
def get_canonical_report(
    report_id: UUID,
    service: CanonicalReportService = Depends(
        get_canonical_report_service
    ),
) -> CanonicalReportResponse:
    try:
        return service.get_run(str(report_id))
    except CalculationIntegrationError as error:
        _translate_error(error)


@router.get(
    "/models/{model_version_id}/reports",
    response_model=CanonicalReportHistoryResponse,
)
def get_canonical_report_history(
    model_version_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    service: CanonicalReportService = Depends(
        get_canonical_report_service
    ),
) -> CanonicalReportHistoryResponse:
    try:
        return service.history(str(model_version_id), limit=limit)
    except CalculationIntegrationError as error:
        _translate_error(error)
