"""Independent PostgreSQL-backed analysis worker."""

from __future__ import annotations

import os
import signal
import time
import uuid

from .calculation_integration_service import CalculationIntegrationService
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


def run_once(worker_id: str) -> bool:
    with SessionLocal() as session:
        service = _service(session)
        service.requeue_stale(
            int(os.getenv("ANALYSIS_STALE_SECONDS", "900"))
        )
        run_id = service.claim_next(worker_id)
    if run_id is None:
        return False
    with SessionLocal() as session:
        _service(session).process_claimed(run_id)
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
