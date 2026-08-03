"""Read-only catalog of canonical model versions available for restoration."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .calculation_rules.phase2_models import CalculationRunRecord
from .model_extraction_models import ModelVersion
from .schemas import ModelHistoryItem, ModelHistoryResponse


_COMPLETED_RUN_STATUSES = ("completed", "completed_with_warning")


class ModelHistoryService:
    """Project persisted model versions into the Upload-page history contract."""

    def __init__(self, session: Session):
        self._session = session

    def list_recent(self, limit: int) -> ModelHistoryResponse:
        models = list(
            self._session.scalars(
                select(ModelVersion)
                .options(joinedload(ModelVersion.workbook_version))
                .where(
                    ModelVersion.status == "materialized",
                    ModelVersion.submitted.is_(True),
                )
                .order_by(
                    ModelVersion.created_at.desc(),
                    ModelVersion.id.desc(),
                )
                .limit(limit)
            ).unique()
        )
        model_ids = [model.id for model in models]
        baselines_by_model: dict[str, CalculationRunRecord] = {}
        if model_ids:
            runs = self._session.scalars(
                select(CalculationRunRecord)
                .where(
                    CalculationRunRecord.model_version_id.in_(model_ids),
                    CalculationRunRecord.status.in_(
                        _COMPLETED_RUN_STATUSES
                    ),
                )
                .order_by(
                    CalculationRunRecord.created_at.desc(),
                    CalculationRunRecord.id.desc(),
                )
            )
            for run in runs:
                if run.model_version_id in baselines_by_model:
                    continue
                if list(run.overrides_json or []) != []:
                    continue
                baselines_by_model[run.model_version_id] = run

        return ModelHistoryResponse(
            models=[
                self._history_item(model, baselines_by_model.get(model.id))
                for model in models
            ]
        )

    @staticmethod
    def _history_item(
        model: ModelVersion,
        baseline: CalculationRunRecord | None,
    ) -> ModelHistoryItem:
        return ModelHistoryItem(
            model_version_id=model.id,
            workbook_version_id=model.workbook_version_id,
            filename=(
                model.upload_filename
                or model.workbook_version.original_filename
            ),
            updated_at=(
                model.completed_at
                or model.extracted_at
                or model.created_at
            ),
            calculation_status=(
                "baseline_ready"
                if baseline is not None
                else "calculation_required"
            ),
            graph_version_id=(
                baseline.graph_version_id if baseline is not None else None
            ),
            baseline_run_id=(baseline.id if baseline is not None else None),
        )
