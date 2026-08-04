"""Synchronous HTTP endpoints for persona report conversations."""

from __future__ import annotations

from io import BytesIO
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..analysis_presentation_service import AnalysisPresentationService
from ..auth import get_current_user
from ..calculation_integration_service import (
    CalculationIntegrationError,
    CalculationIntegrationService,
)
from ..canonical_report_service import CanonicalReportService
from ..database import get_db
from ..model_extraction_read_service import ModelExtractionReadService
from ..models import User
from ..monte_carlo_service import MonteCarloService
from ..report_chat_docx import ReportChatDocxRenderer
from ..report_chat_evidence import ReportChatEvidenceBuilder
from ..report_chat_generator import (
    ReportChatGenerationError,
    ReportChatGenerator,
)
from ..report_chat_repository import ReportChatRepository
from ..report_chat_schemas import (
    ReportChatExchangeResponse,
    ReportChatMessageCreateRequest,
    ReportChatThreadResponse,
)
from ..report_chat_service import ReportChatNotFound, ReportChatService
from ..workbook_storage import DatabaseWorkbookStorage


router = APIRouter(tags=["Report Chat"])

_DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def get_report_chat_generator() -> ReportChatGenerator:
    return ReportChatGenerator()


def get_report_chat_service(
    session: Session = Depends(get_db),
    generator: ReportChatGenerator = Depends(get_report_chat_generator),
) -> ReportChatService:
    calculation_service = CalculationIntegrationService(
        session,
        ModelExtractionReadService(
            session,
            DatabaseWorkbookStorage(session),
        ),
    )
    canonical_service = CanonicalReportService(
        session,
        calculation_service,
        AnalysisPresentationService(session, calculation_service),
        MonteCarloService(session, calculation_service),
    )
    return ReportChatService(
        ReportChatRepository(session),
        canonical_service,
        ReportChatEvidenceBuilder(),
        generator,
        ReportChatDocxRenderer(),
    )


def report_chat_owner_key(user: User | None, client_id: str) -> str:
    return f"user:{user.id}" if user is not None else f"client:{client_id}"


def _translate_calculation_error(error: CalculationIntegrationError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail=error.detail(),
    ) from error


@router.get(
    "/models/{model_version_id}/report-chat",
    response_model=ReportChatThreadResponse,
)
def get_report_chat_history(
    model_version_id: UUID,
    client_id: UUID = Query(),
    user: User | None = Depends(get_current_user),
    service: ReportChatService = Depends(get_report_chat_service),
) -> ReportChatThreadResponse:
    return service.history(
        str(model_version_id),
        report_chat_owner_key(user, str(client_id)),
    )


@router.post(
    "/models/{model_version_id}/report-chat/messages",
    response_model=ReportChatExchangeResponse,
)
def send_report_chat_message(
    model_version_id: UUID,
    request: ReportChatMessageCreateRequest,
    user: User | None = Depends(get_current_user),
    service: ReportChatService = Depends(get_report_chat_service),
) -> ReportChatExchangeResponse:
    try:
        return service.send(
            str(model_version_id),
            report_chat_owner_key(user, request.client_id),
            request,
        )
    except CalculationIntegrationError as error:
        _translate_calculation_error(error)
    except ReportChatGenerationError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "REPORT_CHAT_GENERATION_FAILED",
                "message": str(error),
            },
        ) from error


@router.get(
    "/models/{model_version_id}/report-chat/messages/{message_id}/docx",
)
def export_report_chat_docx(
    model_version_id: UUID,
    message_id: UUID,
    client_id: UUID = Query(),
    user: User | None = Depends(get_current_user),
    service: ReportChatService = Depends(get_report_chat_service),
) -> StreamingResponse:
    try:
        filename, payload = service.export_docx(
            str(model_version_id),
            report_chat_owner_key(user, str(client_id)),
            str(message_id),
        )
    except ReportChatNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "REPORT_CHAT_NOT_FOUND",
                "message": str(error),
            },
        ) from error
    return StreamingResponse(
        BytesIO(payload),
        media_type=_DOCX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
