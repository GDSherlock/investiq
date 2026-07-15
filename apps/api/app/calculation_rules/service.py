"""Canonical-only orchestration for Phase 1 calculation rule extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy.orm import Session

from ..model_extraction_read_service import ModelExtractionReadService
from ..model_extraction_types import AmbiguousSourceCellError
from .comparison import CachedValueComparator
from .compiler import FormulaCompiler
from .evaluator import FormulaExecution, SafeCalculationEvaluator, scalar_from_python
from .graph import CalculationGraphBuilder, CalculationGraphPlan, expand_reference
from .inventory import WorkbookFormulaInventory
from .repository import (
    CalculationRuleExtractionResult,
    CalculationRuleRepository,
    FormulaCanonicalMappingData,
    FormulaExecutionPersistenceData,
)
from .types import (
    CalculationRuleExtractionConfiguration,
    FormulaCompilation,
    FormulaIdFactory,
    FormulaReference,
    WorkbookCatalog,
    WorkbookCellRef,
    WorkbookFormulaCell,
)


@dataclass(frozen=True)
class _CanonicalTarget:
    entity_kind: str
    entity_id: str
    financial_series_value_id: str | None

    @property
    def identity(self) -> str:
        return "|".join(
            (
                self.entity_kind,
                self.entity_id,
                self.financial_series_value_id or "",
            )
        )


class CanonicalMappingResolver:
    """Attach optional lineage using only canonical read-service methods."""

    def __init__(
        self,
        read_service: ModelExtractionReadService,
        model_version_id: str,
        extraction_id: str,
    ):
        self._read_service = read_service
        self._model_version_id = model_version_id
        self._extraction_id = extraction_id

    def resolve(
        self,
        catalog: WorkbookCatalog,
        compilations: Sequence[FormulaCompilation],
    ) -> tuple[FormulaCanonicalMappingData, ...]:
        formula_by_id = {formula.id: formula for formula in catalog.formulas}
        mappings: list[FormulaCanonicalMappingData] = []
        for compilation in compilations:
            formula = formula_by_id[compilation.formula_cell_id]
            mappings.append(
                self._mapping(
                    formula.id,
                    None,
                    "output",
                    (formula.ref,),
                    (),
                )
            )
            for reference in compilation.references:
                targets = expand_reference(reference, catalog)
                evidence_warnings: tuple[str, ...] = ()
                if reference.resolution_status == "external":
                    evidence_warnings = ("external_reference",)
                elif reference.resolution_status != "resolved_internal":
                    evidence_warnings = (
                        f"reference_{reference.resolution_status}",
                    )
                mappings.append(
                    self._mapping(
                        formula.id,
                        reference,
                        "input",
                        targets,
                        evidence_warnings,
                    )
                )
        return tuple(mappings)

    def _mapping(
        self,
        formula_cell_id: str,
        reference: FormulaReference | None,
        role: str,
        targets: Sequence[WorkbookCellRef],
        evidence_warnings: tuple[str, ...],
    ) -> FormulaCanonicalMappingData:
        resolved: list[_CanonicalTarget] = []
        ambiguous = False
        unresolved_count = 0
        for target in targets:
            try:
                resolution = self._read_service.resolve_entity_by_source_cell(
                    self._model_version_id,
                    target.sheet_name,
                    target.cell_address,
                )
            except AmbiguousSourceCellError:
                ambiguous = True
                continue
            if resolution is None:
                unresolved_count += 1
                continue
            resolved.append(
                _CanonicalTarget(
                    entity_kind=resolution.entity.entity_kind,
                    entity_id=resolution.entity.id,
                    financial_series_value_id=(
                        getattr(getattr(resolution, "value", None), "id", None)
                    ),
                )
            )

        unique_targets = {target.identity: target for target in resolved}
        warnings = list(evidence_warnings)
        selected: _CanonicalTarget | None = None
        if ambiguous or len(unique_targets) > 1:
            mapping_status = "ambiguous"
            warnings.append("canonical_mapping_ambiguous")
        elif len(unique_targets) == 1:
            mapping_status = "mapped"
            selected = next(iter(unique_targets.values()))
            if unresolved_count:
                warnings.append("range_partially_mapped")
        else:
            mapping_status = "unmapped"
            warnings.append("canonical_mapping_missing")

        reference_id = reference.id if reference is not None else None
        target_id = selected.identity if selected is not None else None
        return FormulaCanonicalMappingData(
            id=FormulaIdFactory.mapping_id(
                self._extraction_id,
                formula_cell_id,
                reference_id,
                role,
                target_id,
            ),
            calculation_rule_extraction_id=self._extraction_id,
            formula_cell_id=formula_cell_id,
            reference_id=reference_id,
            mapping_role=role,
            mapping_status=mapping_status,
            entity_kind=selected.entity_kind if selected is not None else None,
            entity_id=selected.entity_id if selected is not None else None,
            financial_series_value_id=(
                selected.financial_series_value_id if selected is not None else None
            ),
            warnings=tuple(dict.fromkeys(warnings)),
        )


class CalculationRuleExtractionService:
    def __init__(
        self,
        session: Session,
        read_service: ModelExtractionReadService,
        *,
        inventory: WorkbookFormulaInventory | None = None,
    ):
        self._session = session
        self._read_service = read_service
        self._repository = CalculationRuleRepository(session)
        self._inventory = inventory

    def extract_and_execute(
        self,
        model_version_id: str,
        workbook_version_id: str,
        configuration: CalculationRuleExtractionConfiguration | None = None,
    ) -> CalculationRuleExtractionResult:
        configuration = configuration or CalculationRuleExtractionConfiguration()
        self._read_service.load_model_version(
            model_version_id,
            require_materialized=True,
            expected_workbook_version_id=workbook_version_id,
        )
        extraction_id = FormulaIdFactory.extraction_id(
            model_version_id,
            workbook_version_id,
            configuration,
        )
        completed = self._repository.load_completed_result(extraction_id)
        if completed is not None:
            return completed

        workbook = self._read_service.load_workbook_version(workbook_version_id)
        self._repository.start_run(
            extraction_id,
            model_version_id,
            workbook_version_id,
            configuration,
        )
        self._session.commit()

        try:
            inventory = self._inventory or WorkbookFormulaInventory(configuration)
            catalog = inventory.scan(workbook.content_bytes, workbook_version_id)
            compiler = FormulaCompiler(configuration)
            compilations = tuple(
                compiler.compile(formula, catalog) for formula in catalog.formulas
            )
            self._repository.save_compilation(
                catalog,
                compilations,
                configuration,
            )
            self._session.commit()

            mappings = CanonicalMappingResolver(
                self._read_service,
                model_version_id,
                extraction_id,
            ).resolve(catalog, compilations)
            graph_plan = CalculationGraphBuilder(configuration).build(
                catalog,
                compilations,
            )
            executions = SafeCalculationEvaluator().execute(
                graph_plan,
                catalog,
                compilations,
                configuration,
            )
            persisted_results = self._execution_rows(
                extraction_id,
                catalog,
                compilations,
                executions,
                configuration,
            )
            summary, warnings = self._summary(
                catalog,
                compilations,
                mappings,
                graph_plan,
                persisted_results,
            )
            status = "completed_with_warning" if warnings else "completed"
            self._repository.replace_outputs(
                extraction_id,
                mappings,
                persisted_results,
                configuration,
            )
            self._repository.complete_run(
                extraction_id,
                status=status,
                summary=summary,
                warnings=warnings,
            )
            self._session.commit()
            return self._repository.load_result(extraction_id)
        except Exception:
            self._session.rollback()
            try:
                self._repository.mark_failed(
                    extraction_id,
                    "CALCULATION_RULE_EXTRACTION_FAILED",
                    "Calculation rule extraction failed",
                )
                self._session.commit()
            except Exception:
                self._session.rollback()
            raise

    @staticmethod
    def _execution_rows(
        extraction_id: str,
        catalog: WorkbookCatalog,
        compilations: Sequence[FormulaCompilation],
        executions: dict[WorkbookCellRef, FormulaExecution],
        configuration: CalculationRuleExtractionConfiguration,
    ) -> tuple[FormulaExecutionPersistenceData, ...]:
        formula_by_ref = catalog.formula_by_ref()
        compilation_by_cell = {
            compilation.formula_cell_id: compilation for compilation in compilations
        }
        comparator = CachedValueComparator(configuration)
        rows: list[FormulaExecutionPersistenceData] = []
        for reference, formula in sorted(
            formula_by_ref.items(),
            key=lambda item: (
                item[0].sheet_position,
                item[0].cell_address,
            ),
        ):
            execution = executions[reference]
            cached = (
                scalar_from_python(
                    formula.cached_value,
                    formula.cached_value_type,
                    catalog.workbook_date_system,
                )
                if formula.cache_status == "available"
                else None
            )
            comparison = comparator.compare(
                execution.value,
                cached,
                formula.cache_freshness,
            )
            compilation = compilation_by_cell[formula.id]
            rows.append(
                FormulaExecutionPersistenceData(
                    id=FormulaIdFactory.execution_result_id(
                        extraction_id,
                        formula.id,
                    ),
                    calculation_rule_extraction_id=extraction_id,
                    formula_cell_id=formula.id,
                    expression_id=compilation.expression_id,
                    execution=execution,
                    comparison=comparison,
                )
            )
        return tuple(rows)

    @staticmethod
    def _summary(
        catalog: WorkbookCatalog,
        compilations: Sequence[FormulaCompilation],
        mappings: Sequence[FormulaCanonicalMappingData],
        graph_plan: CalculationGraphPlan,
        results: Sequence[FormulaExecutionPersistenceData],
    ) -> tuple[dict[str, object], tuple[str, ...]]:
        executed = sum(row.execution.status == "executed" for row in results)
        execution_errors = sum(
            row.execution.status == "execution_error" for row in results
        )
        supported = sum(
            compilation.support_status == "supported"
            for compilation in compilations
        )
        unsupported = sum(
            compilation.support_status == "unsupported"
            for compilation in compilations
        )
        external = sum(
            compilation.support_status == "external_reference"
            for compilation in compilations
        )
        special = sum(
            compilation.support_status == "special_formula"
            for compilation in compilations
        )
        parsed = sum(
            compilation.parse_status == "parsed" for compilation in compilations
        )
        matched = sum(
            row.comparison.validation_status == "matched" for row in results
        )
        mismatched = sum(
            row.comparison.validation_status == "mismatched" for row in results
        )
        no_cache = sum(
            row.comparison.validation_status == "no_cached_value"
            for row in results
        )
        blocked = sum(
            row.execution.status == "blocked_by_dependency" for row in results
        )

        all_references = [
            reference
            for compilation in compilations
            for reference in compilation.references
        ]
        internal_references = [
            reference
            for reference in all_references
            if reference.target_classification != "external"
        ]
        resolved_internal = sum(
            reference.resolution_status == "resolved_internal"
            for reference in internal_references
        )
        eligible_mappings = [
            mapping
            for mapping in mappings
            if "external_reference" not in mapping.warnings
        ]
        mapped = sum(
            mapping.mapping_status == "mapped" for mapping in eligible_mappings
        )
        executable_attempts = executed + execution_errors
        comparable_caches = matched + mismatched
        metrics = {
            "supported_formula_parse_rate": _rate(supported, supported),
            "supported_formula_execution_rate": _rate(
                executed,
                executable_attempts,
            ),
            "cached_value_match_rate": _rate(matched, comparable_caches),
            "internal_reference_resolution_rate": _rate(
                resolved_internal,
                len(internal_references),
            ),
            "canonical_mapping_rate": _rate(mapped, len(eligible_mappings)),
        }
        summary: dict[str, object] = {
            "formula_cells_total": len(catalog.formulas),
            "formula_cells_parsed": parsed,
            "formula_cells_executable": supported,
            "formula_cells_executed": executed,
            "cached_values_matched": matched,
            "cached_values_mismatched": mismatched,
            "unsupported_formula_cells": unsupported,
            "external_reference_cells": external,
            "special_formula_cells": special,
            "cycles_detected": len(graph_plan.cycles),
            "blocked_formula_cells": blocked,
            "execution_error_cells": execution_errors,
            "missing_cached_values": no_cache,
            "metric_denominators": {
                "formula_cells_supported_by_whitelist": supported,
                "parsed_supported_acyclic_unblocked": executable_attempts,
                "comparable_executed_with_cache": comparable_caches,
                "internal_reference_tokens": len(internal_references),
                "eligible_canonical_mapping_occurrences": len(eligible_mappings),
            },
            "metric_numerators": {
                "parsed_supported": supported,
                "executed": executed,
                "cached_values_matched": matched,
                "resolved_internal_references": resolved_internal,
                "mapped_canonical_mapping_occurrences": mapped,
            },
            "metrics": metrics,
        }
        warnings: list[str] = []
        if unsupported:
            warnings.append("unsupported_formula_cells")
        if external:
            warnings.append("external_reference_cells")
        if special:
            warnings.append("special_formula_cells")
        if graph_plan.cycles:
            warnings.append("cycles_detected")
        if blocked:
            warnings.append("blocked_by_dependency")
        if execution_errors:
            warnings.append("execution_errors")
        if no_cache:
            warnings.append("missing_cached_values")
        if mismatched:
            warnings.append("cached_value_mismatches")
        if any(mapping.mapping_status != "mapped" for mapping in eligible_mappings):
            warnings.append("canonical_lineage_incomplete")
        return summary, tuple(warnings)


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator
