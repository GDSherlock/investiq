"""Independent PostgreSQL-backed analysis worker."""

from __future__ import annotations

import os
import signal
import time
import uuid

from .calculation_integration_service import CalculationIntegrationService
from .analysis_presentation_service import AnalysisPresentationService
from .canonical_report_service import CanonicalReportService
from .database import SessionLocal
from .model_extraction_read_service import ModelExtractionReadService
from .monte_carlo_service import MonteCarloService
from .workbook_storage import DatabaseWorkbookStorage


def _service(session) -> MonteCarloService:
    calculation_service = CalculationIntegrationService(
        session,
        ModelExtractionReadService(
            session,
            DatabaseWorkbookStorage(session),
        ),
    )
    return MonteCarloService(session, calculation_service)


def _report_service(session) -> CanonicalReportService:
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


def run_once(worker_id: str) -> bool:
    with SessionLocal() as session:
        service = _service(session)
        report_service = _report_service(session)
        stale_seconds = int(os.getenv("ANALYSIS_STALE_SECONDS", "900"))
        service.requeue_stale(stale_seconds)
        report_service.requeue_stale(stale_seconds)
        run_id = service.claim_next(worker_id)
        report_id = (
            None
            if run_id is not None
            else report_service.claim_next(worker_id)
        )
    if run_id is not None:
        with SessionLocal() as session:
            _service(session).process_claimed(run_id)
        return True
    if report_id is None:
        return False
    with SessionLocal() as session:
        _report_service(session).process_claimed(report_id)
    return True


def main() -> None:
    worker_id = os.getenv(
        "ANALYSIS_WORKER_ID",
        f"analysis-worker-{uuid.uuid4()}",
    )
    poll_seconds = float(os.getenv("ANALYSIS_POLL_SECONDS", "1"))
    stopping = False

    def stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        if not run_once(worker_id):
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
