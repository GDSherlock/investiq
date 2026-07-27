"""Thin HTTP routes for deterministic calculation integration."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..calculation_integration_service import (
    CalculationIntegrationError,
    CalculationIntegrationService,
)
from ..calculation_sensitivity_service import CalculationSensitivityService
from ..database import get_db
from ..model_extraction_read_service import ModelExtractionReadService
from ..schemas import (
    CalculationInputsResponse,
    CalculationOutputsResponse,
    CalculationPrepareRequest,
    CalculationReadinessResponse,
    CalculationRequest,
    CalculationRunOutputsResponse,
    CalculationRunResponse,
    CalculationSensitivityRequest,
    CalculationSensitivityResponse,
)
from ..workbook_storage import DatabaseWorkbookStorage


router = APIRouter(tags=["Calculation"])


def get_calculation_integration_service(
    session: Session = Depends(get_db),
) -> CalculationIntegrationService:
    read_service = ModelExtractionReadService(
        session,
        DatabaseWorkbookStorage(session),
    )
    return CalculationIntegrationService(session, read_service)


def get_calculation_sensitivity_service(
    session: Session = Depends(get_db),
    calculation_service: CalculationIntegrationService = Depends(
        get_calculation_integration_service
    ),
) -> CalculationSensitivityService:
    return CalculationSensitivityService(session, calculation_service)


def _translate_error(error: CalculationIntegrationError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail=error.detail(),
    ) from error


@router.get(
    "/models/{model_version_id}/calculation/readiness",
    response_model=CalculationReadinessResponse,
)
def get_calculation_readiness(
    model_version_id: UUID,
    service: CalculationIntegrationService = Depends(
        get_calculation_integration_service
    ),
) -> CalculationReadinessResponse:
    try:
        return service.get_readiness(str(model_version_id))
    except CalculationIntegrationError as error:
        _translate_error(error)


@router.post(
    "/models/{model_version_id}/calculation/prepare",
    response_model=CalculationReadinessResponse,
)
def prepare_calculation(
    model_version_id: UUID,
    _request: CalculationPrepareRequest | None = Body(default=None),
    service: CalculationIntegrationService = Depends(
        get_calculation_integration_service
    ),
) -> CalculationReadinessResponse:
    try:
        return service.prepare(str(model_version_id))
    except CalculationIntegrationError as error:
        _translate_error(error)


@router.get(
    "/models/{model_version_id}/calculation/inputs",
    response_model=CalculationInputsResponse,
)
def get_calculation_inputs(
    model_version_id: UUID,
    target_kind: Literal["parameter", "financial_series_value"] = "parameter",
    editable_only: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = None,
    service: CalculationIntegrationService = Depends(
        get_calculation_integration_service
    ),
) -> CalculationInputsResponse:
    try:
        return service.list_inputs(
            str(model_version_id),
            target_kind=target_kind,
            editable_only=editable_only,
            limit=limit,
            cursor=cursor,
        )
    except CalculationIntegrationError as error:
        _translate_error(error)


@router.get(
    "/models/{model_version_id}/calculation/outputs",
    response_model=CalculationOutputsResponse,
)
def get_calculation_outputs(
    model_version_id: UUID,
    service: CalculationIntegrationService = Depends(
        get_calculation_integration_service
    ),
) -> CalculationOutputsResponse:
    try:
        return service.list_outputs(str(model_version_id))
    except CalculationIntegrationError as error:
        _translate_error(error)


@router.post(
    "/models/{model_version_id}/calculation/sensitivity",
    response_model=CalculationSensitivityResponse,
)
def analyze_calculation_sensitivity(
    model_version_id: UUID,
    request: CalculationSensitivityRequest,
    service: CalculationSensitivityService = Depends(
        get_calculation_sensitivity_service
    ),
) -> CalculationSensitivityResponse:
    try:
        return service.analyze(str(model_version_id), request)
    except CalculationIntegrationError as error:
        _translate_error(error)


@router.get(
    "/calculation-sensitivity-analyses/{analysis_id}",
    response_model=CalculationSensitivityResponse,
)
def get_calculation_sensitivity_analysis(
    analysis_id: UUID,
    service: CalculationSensitivityService = Depends(
        get_calculation_sensitivity_service
    ),
) -> CalculationSensitivityResponse:
    try:
        return service.get_analysis(str(analysis_id))
    except CalculationIntegrationError as error:
        _translate_error(error)


@router.post(
    "/models/{model_version_id}/calculations",
    response_model=CalculationRunResponse,
)
def calculate_model(
    model_version_id: UUID,
    request: CalculationRequest,
    service: CalculationIntegrationService = Depends(
        get_calculation_integration_service
    ),
) -> CalculationRunResponse:
    try:
        return service.calculate(str(model_version_id), request)
    except CalculationIntegrationError as error:
        _translate_error(error)


@router.get(
    "/calculation-runs/{calculation_run_id}",
    response_model=CalculationRunResponse,
)
def get_calculation_run(
    calculation_run_id: UUID,
    service: CalculationIntegrationService = Depends(
        get_calculation_integration_service
    ),
) -> CalculationRunResponse:
    try:
        return service.get_run(str(calculation_run_id))
    except CalculationIntegrationError as error:
        _translate_error(error)


@router.get(
    "/calculation-runs/{calculation_run_id}/outputs",
    response_model=CalculationRunOutputsResponse,
)
def get_calculation_run_outputs(
    calculation_run_id: UUID,
    service: CalculationIntegrationService = Depends(
        get_calculation_integration_service
    ),
) -> CalculationRunOutputsResponse:
    try:
        return service.get_run_outputs(str(calculation_run_id))
    except CalculationIntegrationError as error:
        _translate_error(error)
