from __future__ import annotations

from pathlib import Path
import uuid

from apps.api.app.canonical_report_generator import (
    CANONICAL_IC_SECTION_KEYS,
    generate_canonical_report,
)
from apps.api.app.schemas import CanonicalReportCreateRequest


def _uuid() -> str:
    return str(uuid.uuid4())


def test_report_request_freezes_only_canonical_analysis_identities() -> None:
    request = CanonicalReportCreateRequest.model_validate(
        {
            "graph_version_id": _uuid(),
            "calculation_run_id": _uuid(),
            "sensitivity_analysis_id": _uuid(),
            "monte_carlo_run_id": _uuid(),
            "template_version": "canonical-ic-paper-v1",
            "persona": {
                "id": "IM",
                "name": "Investment Manager",
                "tone": "Formal, IC-ready",
                "emphasis": ["returns", "covenants"],
            },
            "idempotency_key": "canonical-report-test",
        }
    )

    assert request.calculation_run_id
    assert request.sensitivity_analysis_id
    assert request.monte_carlo_run_id
    assert "model_snapshot_id" not in request.model_dump()


def test_generator_keeps_thirteen_sections_and_pending_recommendation() -> None:
    calculation_run_id = _uuid()
    artifact = generate_canonical_report(
        {
            "model": {
                "model_version_id": _uuid(),
                "upload_filename": "Project.xlsx",
            },
            "calculation": {
                "calculation_run_id": calculation_run_id,
                "overview": {"kpis": [], "charts": []},
                "cash_flow": {"charts": []},
            },
            "assumptions": [],
            "sensitivity": None,
            "monte_carlo": None,
            "template": {
                "id": "investment-committee-paper",
                "version": "canonical-ic-paper-v1",
            },
            "persona": {
                "id": "IM",
                "name": "Investment Manager",
                "tone": "Formal",
                "emphasis": [],
            },
            "evidence_hash": "a" * 64,
        }
    )

    assert [section["key"] for section in artifact["sections"]] == list(
        CANONICAL_IC_SECTION_KEYS
    )
    assert len(artifact["sections"]) == 13
    assert artifact["final_recommendation"] == "Pending IC review"
    assert artifact["sections"][8]["availability_status"] == "unavailable"
    assert artifact["sections"][9]["availability_status"] == "unavailable"
    assert artifact["sections"][11]["availability_status"] == "unavailable"
    assert artifact["sections"][12]["body"] == "Pending IC review"


def test_report_migration_creates_queue_and_immutable_artifact() -> None:
    migration = Path(
        "apps/api/alembic/versions/"
        "20260728_0009_canonical_report_artifacts.py"
    ).read_text()

    assert 'revision: str = "20260728_0009"' in migration
    assert 'down_revision: Union[str, Sequence[str], None] = "20260728_0008"' in migration
    assert '"canonical_report_runs"' in migration
    assert '"canonical_report_artifacts"' in migration
    assert '"calculation_run_id"' in migration
    assert '"sensitivity_analysis_id"' in migration
    assert '"monte_carlo_run_id"' in migration
    assert '"frozen_evidence_json"' in migration
    assert '"evidence_hash"' in migration
