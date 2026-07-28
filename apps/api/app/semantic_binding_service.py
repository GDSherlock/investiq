"""Reviewed canonical UUID bindings for analysis presentation roles."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

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
