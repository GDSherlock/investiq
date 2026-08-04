"""Preview or apply missing Project FCF semantic bindings."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import uuid
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .model_extraction_models import (
    FinancialSeries,
    FinancialSeriesValue,
    ModelSemanticBinding,
    ModelVersion,
)
from .semantic_binding_service import build_extracted_semantic_bindings


@dataclass(frozen=True)
class ProjectFcfBindingBackfillResult:
    model_version_id: str
    action: Literal["insert", "skip_existing", "skip_no_candidate"]
    selected_series_id: str | None
    evidence: dict[str, Any] | None


def _row_dict(row: Any) -> dict[str, Any]:
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
    }


def preview_project_fcf_binding(
    session: Session,
    model_version_id: str,
) -> ProjectFcfBindingBackfillResult:
    existing = session.scalar(
        select(ModelSemanticBinding).where(
            ModelSemanticBinding.model_version_id == model_version_id,
            ModelSemanticBinding.semantic_role == "project_free_cash_flow",
        )
    )
    if existing is not None:
        return ProjectFcfBindingBackfillResult(
            model_version_id=model_version_id,
            action="skip_existing",
            selected_series_id=existing.financial_series_id,
            evidence=existing.evidence_json,
        )

    series = list(
        session.scalars(
            select(FinancialSeries)
            .where(FinancialSeries.model_version_id == model_version_id)
            .order_by(FinancialSeries.id)
        )
    )
    series_ids = [item.id for item in series]
    values = (
        list(
            session.scalars(
                select(FinancialSeriesValue)
                .where(FinancialSeriesValue.financial_series_id.in_(series_ids))
                .order_by(
                    FinancialSeriesValue.financial_series_id,
                    FinancialSeriesValue.period_index,
                )
            )
        )
        if series_ids
        else []
    )
    bindings = build_extracted_semantic_bindings(
        model_version_id,
        outputs=[],
        financial_series=[_row_dict(item) for item in series],
        financial_series_values=[_row_dict(item) for item in values],
        parameters=[],
    )
    selected = next(
        (
            row
            for row in bindings
            if row["semantic_role"] == "project_free_cash_flow"
        ),
        None,
    )
    if selected is None:
        return ProjectFcfBindingBackfillResult(
            model_version_id=model_version_id,
            action="skip_no_candidate",
            selected_series_id=None,
            evidence=None,
        )
    return ProjectFcfBindingBackfillResult(
        model_version_id=model_version_id,
        action="insert",
        selected_series_id=str(selected["financial_series_id"]),
        evidence=selected["evidence_json"],
    )


def apply_project_fcf_binding(
    session: Session,
    model_version_id: str,
) -> ProjectFcfBindingBackfillResult:
    result = preview_project_fcf_binding(session, model_version_id)
    if result.action != "insert" or result.selected_series_id is None:
        return result
    binding_id = str(
        uuid.uuid5(
            uuid.UUID(model_version_id),
            "semantic_binding:project_free_cash_flow",
        )
    )
    session.add(
        ModelSemanticBinding(
            id=binding_id,
            model_version_id=model_version_id,
            semantic_role="project_free_cash_flow",
            financial_series_id=result.selected_series_id,
            binding_source="extracted",
            evidence_json=result.evidence,
        )
    )
    session.flush()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    with SessionLocal() as catalog_session:
        model_ids = list(
            catalog_session.scalars(
                select(ModelVersion.id)
                .where(ModelVersion.status == "materialized")
                .order_by(ModelVersion.created_at, ModelVersion.id)
            )
        )
    for model_id in model_ids:
        with SessionLocal() as session:
            try:
                result = (
                    apply_project_fcf_binding(session, model_id)
                    if arguments.apply
                    else preview_project_fcf_binding(session, model_id)
                )
                if arguments.apply:
                    session.commit()
                else:
                    session.rollback()
                print(json.dumps(asdict(result), sort_keys=True))
            except Exception:
                session.rollback()
                raise


if __name__ == "__main__":
    main()
