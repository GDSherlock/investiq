"""Reviewed canonical UUID bindings for analysis presentation roles."""

from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any, Literal
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .calculation_integration_service import CalculationIntegrationError
from .model_extraction_models import (
    CanonicalOutput,
    FinancialSeries,
    ModelParameter,
    ModelSemanticBinding,
    ModelVersion,
)
from .model_extraction_types import SEMANTIC_BINDING_ROLES, new_uuid
from .schemas import (
    ParameterAnalysisReviewRequest,
    ParameterAnalysisReviewResponse,
    SemanticBindingEntityItem,
    SemanticBindingReviewRequest,
    SemanticBindingSlotItem,
    SemanticBindingsPreviewResponse,
)


EntityKind = Literal["canonical_output", "financial_series", "model_parameter"]

_OUTPUT_ROLE_BY_SEMANTIC = {
    "project_irr": "project_irr",
    "equity_irr": "equity_irr",
    "project_npv": "npv",
    "equity_npv": "npv",
    "payback_period": "payback_period",
    "minimum_dscr": "minimum_dscr",
    "average_dscr": "average_dscr",
    "equity_multiple": "equity_multiple",
    "debt_to_equity_ratio": "debt_to_equity_ratio",
    "total_debt": "total_debt",
    "total_equity": "total_equity",
    "debt_ratio": "debt_ratio",
    "equity_ratio": "equity_ratio",
}

_SERIES_ROLES = {
    "revenue",
    "ebitda",
    "cfads",
    "project_free_cash_flow",
    "equity_cash_flow",
    "operating_cash_flow",
    "debt_service",
    "dscr",
    "dscr_covenant",
    "closing_debt",
    "capex",
    "interest_expense",
    "principal_repayment",
}

_PARAMETER_ROLES = {
    "discount_rate",
    "project_irr_hurdle",
    "equity_irr_hurdle",
    "dscr_covenant",
    "debt_ratio",
    "equity_ratio",
}

_PROJECT_FCF_STRONG_LABELS = {
    "project free cash flow",
    "project fcf",
    "unlevered project cash flow",
}
_PROJECT_FCF_GENERIC_LABELS = {"project cash flow", "project cf"}
_PROJECT_FCF_COMPATIBLE_ROLES = {"cash_flow", "cfads"}

_SEMANTIC_LABEL_ALIASES = {
    "project_irr": {"project irr"},
    "equity_irr": {"equity irr"},
    "project_npv": {"project npv"},
    "equity_npv": {"equity npv"},
    "minimum_dscr": {"minimum dscr"},
    "average_dscr": {"average dscr"},
    "revenue": {"revenue", "total revenue"},
    "ebitda": {"ebitda"},
    "cfads": {"cfads"},
    "dscr": {"dscr"},
}
_TRAILING_UNIT = re.compile(
    r"\s*\((?:\$?\s*(?:m|mm|million)|(?:usd|sgd|eur|gbp)\s*(?:m|mm|million)|%|x)\)\s*$",
    re.IGNORECASE,
)
_DIRECT_REFERENCE = re.compile(
    r"^=\s*(?:'(?:[^']|'')+'|[A-Za-z0-9_. -]+)?!?\$?[A-Z]{1,3}\$?\d+\s*$"
)


def build_extracted_semantic_bindings(
    model_version_id: str,
    *,
    outputs: list[dict[str, Any]],
    financial_series: list[dict[str, Any]],
    financial_series_values: list[dict[str, Any]],
    parameters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Select one deterministic persisted entity for each semantic role."""

    values_by_series: dict[str, list[dict[str, Any]]] = {}
    for value in financial_series_values:
        values_by_series.setdefault(str(value["financial_series_id"]), []).append(value)

    candidates_by_role: dict[str, list[dict[str, Any]]] = {}
    for semantic_role in SEMANTIC_BINDING_ROLES:
        output_role = _OUTPUT_ROLE_BY_SEMANTIC.get(semantic_role)
        if output_role is not None:
            for output in outputs:
                if output.get("business_role") == output_role:
                    _append_scored_candidate(
                        candidates_by_role,
                        semantic_role,
                        "canonical_output",
                        output,
                        exact_role=True,
                        pure_alias=False,
                    )
        if semantic_role in _SERIES_ROLES:
            for series in financial_series:
                exact_role = series.get("business_role") == semantic_role
                normalized_label = _normalized_label(
                    str(series.get("label") or "")
                )
                compatible_dscr = (
                    semantic_role == "dscr"
                    and series.get("business_role") == "minimum_dscr"
                    and normalized_label == "dscr"
                    and len(values_by_series.get(str(series["id"]), [])) > 1
                )
                compatible_project_fcf = (
                    semantic_role == "project_free_cash_flow"
                    and series.get("business_role")
                    in _PROJECT_FCF_COMPATIBLE_ROLES
                    and normalized_label
                    in _PROJECT_FCF_STRONG_LABELS
                    | _PROJECT_FCF_GENERIC_LABELS
                    and (
                        series.get("business_role") != "cfads"
                        or normalized_label in _PROJECT_FCF_STRONG_LABELS
                    )
                )
                if (
                    not exact_role
                    and not compatible_dscr
                    and not compatible_project_fcf
                ):
                    continue
                points = values_by_series.get(str(series["id"]), [])
                pure_alias = bool(points) and all(
                    isinstance(point.get("exact_formula"), str)
                    and _DIRECT_REFERENCE.fullmatch(str(point["exact_formula"]))
                    for point in points
                )
                _append_scored_candidate(
                    candidates_by_role,
                    semantic_role,
                    "financial_series",
                    series,
                    exact_role=exact_role,
                    pure_alias=pure_alias,
                    semantic_label_score=(
                        40
                        if compatible_project_fcf
                        and normalized_label in _PROJECT_FCF_STRONG_LABELS
                        else 20
                        if compatible_project_fcf
                        else None
                    ),
                )
        if semantic_role in _PARAMETER_ROLES:
            for parameter in parameters:
                if parameter.get("business_role") == semantic_role:
                    _append_scored_candidate(
                        candidates_by_role,
                        semantic_role,
                        "model_parameter",
                        parameter,
                        exact_role=True,
                        pure_alias=False,
                    )

    namespace = uuid.UUID(model_version_id)
    rows: list[dict[str, Any]] = []
    for semantic_role, candidates in sorted(candidates_by_role.items()):
        ranked = sorted(
            candidates,
            key=lambda item: (
                -int(item["score"]),
                str(item["source"]),
                str(item["entity_id"]),
            ),
        )
        selected = ranked[0]
        alternatives = [
            {
                "entity_kind": item["entity_kind"],
                "entity_id": item["entity_id"],
                "source": item["source"],
                "score": item["score"],
                "reasons": item["reasons"],
            }
            for item in ranked[1:]
        ]
        margin = (
            int(selected["score"]) - int(ranked[1]["score"])
            if len(ranked) > 1
            else None
        )
        quality = (
            "high"
            if margin is None or margin >= 30
            else "medium"
            if margin >= 10
            else "low"
        )
        row = {
            "id": str(
                uuid.uuid5(namespace, f"semantic_binding:{semantic_role}")
            ),
            "model_version_id": model_version_id,
            "semantic_role": semantic_role,
            "canonical_output_id": None,
            "financial_series_id": None,
            "model_parameter_id": None,
            "binding_source": "extracted",
            "evidence_json": {
                "selection_method": "deterministic_best_match",
                "selected_score": selected["score"],
                "selected_source": selected["source"],
                "reasons": selected["reasons"],
                "alternatives": alternatives,
                "score_margin": margin,
                "selection_quality": quality,
                "tie_breaker_used": margin == 0,
            },
        }
        row[f"{selected['entity_kind']}_id"] = selected["entity_id"]
        rows.append(row)
    return rows


def _append_scored_candidate(
    candidates_by_role: dict[str, list[dict[str, Any]]],
    semantic_role: str,
    entity_kind: EntityKind,
    entity: dict[str, Any],
    *,
    exact_role: bool,
    pure_alias: bool,
    semantic_label_score: int | None = None,
) -> None:
    score = 100 if exact_role else 70
    reasons = ["exact_business_role" if exact_role else "compatible_business_role"]
    score += 35
    reasons.append("entity_kind_match")
    label = _normalized_label(str(entity.get("label") or ""))
    if semantic_label_score is not None:
        score += semantic_label_score
        reasons.append(
            "strong_project_fcf_label"
            if semantic_label_score == 40
            else "generic_project_fcf_label"
        )
    elif label in _SEMANTIC_LABEL_ALIASES.get(semantic_role, set()):
        score += 30
        reasons.append("exact_label")
    formula_status = str(entity.get("formula_status") or "")
    if formula_status == "formula_with_cached_value" or entity.get("raw_value_json") is not None:
        score += 25
        reasons.append("workbook_value_available")
    validation_status = str(entity.get("validation_status") or "")
    if validation_status and validation_status != "rejected":
        score += 20
        reasons.append("validation_accepted")
    if entity.get("unit") is not None:
        score += 15
        reasons.append("unit_available")
    warnings = entity.get("validation_warnings_json") or []
    if any(str(item).startswith("BEST_MATCH_SOURCE_BUCKET:review_candidates") for item in warnings):
        score -= 5
        reasons.append("review_origin_penalty")
    if pure_alias:
        score -= 15
        reasons.append("direct_reference_alias_penalty")
    if entity_kind == "canonical_output":
        source = f"{entity.get('source_sheet')}!{entity.get('source_cell')}"
    elif entity_kind == "financial_series":
        source = str(entity.get("value_source_range") or entity.get("id"))
    else:
        source = f"{entity.get('source_sheet')}!{entity.get('source_cell')}"
    candidates_by_role.setdefault(semantic_role, []).append(
        {
            "entity_kind": entity_kind,
            "entity_id": str(entity["id"]),
            "source": source,
            "score": score,
            "reasons": reasons,
        }
    )


def _normalized_label(label: str) -> str:
    return " ".join(_TRAILING_UNIT.sub("", label.strip()).casefold().split())


class SemanticBindingService:
    """Resolve only exact persisted business roles; never infer from labels."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def preview(self, model_version_id: str) -> SemanticBindingsPreviewResponse:
        self._load_model(model_version_id)
        bindings = {
            binding.semantic_role: binding
            for binding in self._session.scalars(
                select(ModelSemanticBinding).where(
                    ModelSemanticBinding.model_version_id == model_version_id
                )
            )
        }
        slots: list[SemanticBindingSlotItem] = []
        for semantic_role in SEMANTIC_BINDING_ROLES:
            binding = bindings.get(semantic_role)
            candidates = self._candidates(model_version_id, semantic_role)
            if binding is not None:
                slots.append(
                    SemanticBindingSlotItem(
                        semantic_role=semantic_role,
                        status=binding.binding_source,
                        binding=self._binding_entity(binding),
                        candidates=candidates,
                    )
                )
                continue
            status = (
                "unresolved"
                if not candidates
                else "candidate"
                if len(candidates) == 1
                else "ambiguous"
            )
            slots.append(
                SemanticBindingSlotItem(
                    semantic_role=semantic_role,
                    status=status,
                    binding=None,
                    candidates=candidates,
                )
            )
        return SemanticBindingsPreviewResponse(
            model_version_id=model_version_id,
            slots=slots,
        )

    def review(
        self,
        model_version_id: str,
        semantic_role: str,
        request: SemanticBindingReviewRequest,
    ) -> SemanticBindingSlotItem:
        self._load_model(model_version_id)
        if semantic_role not in SEMANTIC_BINDING_ROLES:
            raise CalculationIntegrationError(
                "SEMANTIC_ROLE_NOT_SUPPORTED",
                "The semantic role is not supported.",
                status_code=404,
                resource_id=semantic_role,
            )
        entity = self._load_entity(
            model_version_id,
            request.entity_kind,
            request.entity_id,
        )
        if not self._matches_role(request.entity_kind, entity, semantic_role):
            raise CalculationIntegrationError(
                "SEMANTIC_ENTITY_ROLE_MISMATCH",
                "The selected canonical entity does not match the semantic role.",
                status_code=409,
                resource_id=request.entity_id,
            )
        binding = self._session.scalar(
            select(ModelSemanticBinding).where(
                ModelSemanticBinding.model_version_id == model_version_id,
                ModelSemanticBinding.semantic_role == semantic_role,
            )
        )
        if binding is None:
            binding = ModelSemanticBinding(
                id=new_uuid(),
                model_version_id=model_version_id,
                semantic_role=semantic_role,
                binding_source="reviewed",
            )
            self._session.add(binding)
        binding.canonical_output_id = None
        binding.financial_series_id = None
        binding.model_parameter_id = None
        setattr(binding, f"{request.entity_kind}_id", request.entity_id)
        binding.binding_source = "reviewed"
        binding.evidence_json = {"review_method": "canonical_uuid"}
        self._session.commit()
        self._session.refresh(binding)
        return SemanticBindingSlotItem(
            semantic_role=semantic_role,
            status="reviewed",
            binding=self._binding_entity(binding),
            candidates=self._candidates(model_version_id, semantic_role),
        )

    def review_parameter(
        self,
        model_version_id: str,
        parameter_id: str,
        request: ParameterAnalysisReviewRequest,
    ) -> ParameterAnalysisReviewResponse:
        parameter = self._load_entity(
            model_version_id,
            "model_parameter",
            parameter_id,
        )
        if request.stochastic_eligible and (
            isinstance(parameter.validated_value_json, bool)
            or not isinstance(parameter.validated_value_json, (int, float))
        ):
            raise CalculationIntegrationError(
                "STOCHASTIC_PARAMETER_NOT_NUMERIC",
                "Only validated numeric parameters can be stochastic eligible.",
                status_code=409,
                resource_id=parameter_id,
            )
        parameter.business_role = request.business_role
        parameter.stochastic_eligible = request.stochastic_eligible
        self._session.commit()
        return ParameterAnalysisReviewResponse(
            model_version_id=model_version_id,
            parameter_id=parameter_id,
            business_role=parameter.business_role,
            stochastic_eligible=parameter.stochastic_eligible,
        )

    def _load_model(self, model_version_id: str) -> ModelVersion:
        model = self._session.get(ModelVersion, model_version_id)
        if model is None:
            raise CalculationIntegrationError(
                "MODEL_VERSION_NOT_FOUND",
                "Model version was not found.",
                status_code=404,
                resource_id=model_version_id,
            )
        return model

    def _load_entity(
        self,
        model_version_id: str,
        entity_kind: EntityKind,
        entity_id: str,
    ) -> CanonicalOutput | FinancialSeries | ModelParameter:
        entity_type = {
            "canonical_output": CanonicalOutput,
            "financial_series": FinancialSeries,
            "model_parameter": ModelParameter,
        }[entity_kind]
        entity = self._session.get(entity_type, entity_id)
        if entity is None or entity.model_version_id != model_version_id:
            raise CalculationIntegrationError(
                "SEMANTIC_ENTITY_NOT_FOUND",
                "The canonical entity does not belong to the model version.",
                status_code=404,
                resource_id=entity_id,
            )
        return entity

    def _candidates(
        self,
        model_version_id: str,
        semantic_role: str,
    ) -> list[SemanticBindingEntityItem]:
        candidates: list[SemanticBindingEntityItem] = []
        output_role = _OUTPUT_ROLE_BY_SEMANTIC.get(semantic_role)
        if output_role is not None:
            rows = self._session.scalars(
                select(CanonicalOutput)
                .where(
                    CanonicalOutput.model_version_id == model_version_id,
                    CanonicalOutput.business_role == output_role,
                )
                .order_by(CanonicalOutput.id)
            )
            candidates.extend(self._entity_items("canonical_output", rows))
        if semantic_role in _SERIES_ROLES:
            rows = self._session.scalars(
                select(FinancialSeries)
                .where(
                    FinancialSeries.model_version_id == model_version_id,
                    FinancialSeries.business_role == semantic_role,
                )
                .order_by(FinancialSeries.id)
            )
            candidates.extend(self._entity_items("financial_series", rows))
        if semantic_role in _PARAMETER_ROLES:
            rows = self._session.scalars(
                select(ModelParameter)
                .where(
                    ModelParameter.model_version_id == model_version_id,
                    ModelParameter.business_role == semantic_role,
                )
                .order_by(ModelParameter.id)
            )
            candidates.extend(self._entity_items("model_parameter", rows))
        return candidates

    def _entity_items(
        self,
        entity_kind: EntityKind,
        entities: Iterable[CanonicalOutput | FinancialSeries | ModelParameter],
    ) -> list[SemanticBindingEntityItem]:
        return [
            SemanticBindingEntityItem(
                entity_kind=entity_kind,
                entity_id=entity.id,
                label=entity.label,
                business_role=getattr(entity, "business_role", None),
                unit=entity.unit,
            )
            for entity in entities
        ]

    def _binding_entity(
        self,
        binding: ModelSemanticBinding,
    ) -> SemanticBindingEntityItem:
        if binding.canonical_output_id is not None:
            kind: EntityKind = "canonical_output"
            entity = binding.canonical_output
        elif binding.financial_series_id is not None:
            kind = "financial_series"
            entity = binding.financial_series
        else:
            kind = "model_parameter"
            entity = binding.model_parameter
        return SemanticBindingEntityItem(
            entity_kind=kind,
            entity_id=entity.id,
            label=entity.label,
            business_role=getattr(entity, "business_role", None),
            unit=entity.unit,
        )

    def _matches_role(
        self,
        entity_kind: EntityKind,
        entity: CanonicalOutput | FinancialSeries | ModelParameter,
        semantic_role: str,
    ) -> bool:
        if entity_kind == "canonical_output":
            return _OUTPUT_ROLE_BY_SEMANTIC.get(semantic_role) == entity.business_role
        if entity_kind == "financial_series":
            return semantic_role in _SERIES_ROLES and (
                entity.business_role == semantic_role
            )
        return semantic_role in _PARAMETER_ROLES and (
            entity.business_role == semantic_role
        )
