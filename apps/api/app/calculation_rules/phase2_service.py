"""Canonical-only compilation and incremental calculation orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
import uuid

from openpyxl.utils.cell import coordinate_to_tuple
from sqlalchemy.orm import Session

from ..model_extraction_read_service import ModelExtractionReadService
from .comparison import CachedValueComparator
from .compiler import FormulaCompiler
from .evaluator import (
    FormulaExecution,
    SafeCalculationEvaluator,
    ScalarValue,
    scalar_from_python,
)
from .graph import CalculationGraphBuilder
from .inventory import WorkbookFormulaInventory
from .phase2_graph import (
    CalculationGraphVersion,
    DirtyPropagator,
    VersionedCalculationGraphBuilder,
)
from .phase2_grouping import BusinessRuleGrouper
from .phase2_registry import PHASE2_FUNCTION_REGISTRY
from .phase2_repository import (
    CalculationRunValueData,
    PersistedCalculationRun,
    Phase2CalculationRepository,
)
from .phase2_types import (
    CalculationCellResult,
    CalculationOverride,
    CalculationRunPolicy,
    CalculationRunResult,
    Phase2CalculationConfiguration,
    WorkbookCompilationResult,
    canonical_hash,
)
from .repository import CalculationRuleRepository
from .types import FormulaCompilation, WorkbookCatalog, WorkbookCellRef


@dataclass(frozen=True)
class _CompiledWorkbook:
    catalog: WorkbookCatalog
    compilations: tuple[FormulaCompilation, ...]
    graph: CalculationGraphVersion


class InternalCalculationEngineService:
    def __init__(
        self,
        session: Session,
        read_service: ModelExtractionReadService,
        *,
        inventory: WorkbookFormulaInventory | None = None,
        evaluator: SafeCalculationEvaluator | None = None,
    ) -> None:
        self._session = session
        self._read_service = read_service
        self._inventory = inventory
        self._evaluator = evaluator or SafeCalculationEvaluator(
            function_registry=PHASE2_FUNCTION_REGISTRY
        )
        self._phase1_repository = CalculationRuleRepository(session)
        self._repository = Phase2CalculationRepository(session)

    def compile_workbook(
        self,
        workbook_version_id: str,
        configuration: Phase2CalculationConfiguration | None = None,
    ) -> WorkbookCompilationResult:
        configuration = configuration or Phase2CalculationConfiguration()
        try:
            compiled = self._compile_workbook(workbook_version_id, configuration)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return self._compilation_result(compiled, configuration)

    def calculate_model(
        self,
        model_version_id: str,
        graph_version_id: str | None = None,
        overrides: Sequence[CalculationOverride] = (),
        run_policy: CalculationRunPolicy | None = None,
        idempotency_key: str | None = None,
        configuration: Phase2CalculationConfiguration | None = None,
    ) -> CalculationRunResult:
        configuration = configuration or Phase2CalculationConfiguration()
        policy = run_policy or CalculationRunPolicy()
        model = self._read_service.load_model_version(
            model_version_id,
            require_materialized=True,
        )
        compiled = self._compile_workbook(
            model.workbook_version_id,
            configuration,
        )
        if graph_version_id is not None and graph_version_id != compiled.graph.id:
            self._session.rollback()
            raise ValueError("Requested graph version does not match the workbook")
        groups = BusinessRuleGrouper(configuration).group(
            model_version_id,
            compiled.catalog,
            compiled.compilations,
        )
        self._repository.save_groups(compiled.graph.id, groups)
        resolved_values, override_payload = self._resolve_overrides(
            model_version_id,
            compiled.catalog,
            overrides,
        )
        normalized_override_hash = canonical_hash(override_payload)
        policy_payload: dict[str, Any] = policy.to_payload()
        if idempotency_key is not None:
            if not idempotency_key.strip():
                raise ValueError("Idempotency key must not be empty")
            policy_payload["idempotency_key"] = idempotency_key
        run_policy_hash = canonical_hash(policy_payload)
        run_id = str(
            uuid.uuid5(
                uuid.UUID(model_version_id),
                "|".join(
                    (
                        compiled.graph.id,
                        configuration.function_registry_version,
                        normalized_override_hash,
                        run_policy_hash,
                    )
                ),
            )
        )
        completed = self._repository.load_completed_run(run_id)
        if completed is not None:
            self._session.commit()
            return self._result_from_persisted(completed, configuration)

        prior = (
            self._repository.find_latest_compatible_run(
                model_version_id,
                compiled.graph.id,
                configuration,
                exclude_run_id=run_id,
            )
            if policy.reuse_compatible_values
            else None
        )
        self._repository.start_run(
            run_id,
            model_version_id,
            compiled.graph.id,
            configuration,
            normalized_override_hash=normalized_override_hash,
            run_policy_hash=run_policy_hash,
            overrides=override_payload,
            run_policy=policy_payload,
            base_run_id=prior.calculation_run_id if prior is not None else None,
        )
        self._session.commit()

        try:
            changed_cells = self._changed_cells(
                compiled.catalog.workbook_version_id,
                override_payload,
                prior.overrides if prior is not None else (),
            )
            dirty = DirtyPropagator().plan(
                compiled.graph,
                changed_cells=changed_cells,
                has_compatible_prior_run=prior is not None,
            )
            prior_by_ref = self._prior_values_by_ref(
                compiled.catalog.workbook_version_id,
                prior,
            )
            reusable = {
                reference
                for reference in dirty.reusable_formula_cells
                if reference in prior_by_ref and prior_by_ref[reference].value is not None
            }
            evaluation_cells = set(dirty.dirty_formula_cells) | (
                set(dirty.reusable_formula_cells) - reusable
            )
            initial_values = {
                reference: prior_by_ref[reference].value
                for reference in reusable
                if prior_by_ref[reference].value is not None
            }
            executions = self._evaluator.execute(
                compiled.graph.base_plan,
                compiled.catalog,
                compiled.compilations,
                configuration,
                evaluation_cells=tuple(evaluation_cells),
                initial_calculated_values=initial_values,
                input_values=resolved_values,
            )
            for reference in reusable:
                executions[reference] = FormulaExecution(
                    status="reused",
                    value=prior_by_ref[reference].value,
                    error_code=None,
                    direct_input_trace=(),
                    warnings=("reused_compatible_value",),
                )
            rows = self._run_values(
                run_id,
                prior.calculation_run_id if prior is not None else None,
                compiled.catalog,
                compiled.compilations,
                executions,
                configuration,
            )
            summary, warnings = self._summary(
                compiled,
                rows,
                len(groups),
                dirty_count=len(evaluation_cells),
            )
            status = "completed_with_warning" if warnings else "completed"
            self._repository.replace_run_values(run_id, rows)
            self._repository.complete_run(
                run_id,
                status=status,
                summary=summary,
                warnings=warnings,
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            try:
                self._repository.mark_failed(
                    run_id,
                    "CALCULATION_ENGINE_V2_FAILED",
                    "Phase 2 calculation failed",
                )
                self._session.commit()
            except Exception:
                self._session.rollback()
            raise
        return self._result_from_persisted(
            self._repository.load_run(run_id),
            configuration,
        )

    def _compile_workbook(
        self,
        workbook_version_id: str,
        configuration: Phase2CalculationConfiguration,
    ) -> _CompiledWorkbook:
        workbook = self._read_service.load_workbook_version(workbook_version_id)
        inventory = self._inventory or WorkbookFormulaInventory(configuration)
        catalog = inventory.scan(workbook.content_bytes, workbook_version_id)
        compiler = FormulaCompiler(
            configuration,
            function_registry=PHASE2_FUNCTION_REGISTRY,
        )
        compilations = tuple(
            compiler.compile(formula, catalog) for formula in catalog.formulas
        )
        self._phase1_repository.save_compilation(
            catalog,
            compilations,
            configuration,
        )
        base_graph = CalculationGraphBuilder(configuration).build(
            catalog,
            compilations,
        )
        graph = VersionedCalculationGraphBuilder(configuration).build(
            catalog,
            compilations,
            base_graph,
        )
        self._repository.save_graph(graph, configuration)
        return _CompiledWorkbook(catalog, compilations, graph)

    def _resolve_overrides(
        self,
        model_version_id: str,
        catalog: WorkbookCatalog,
        overrides: Sequence[CalculationOverride],
    ) -> tuple[dict[WorkbookCellRef, ScalarValue], tuple[dict[str, Any], ...]]:
        parameter_by_id = {
            parameter.id: parameter
            for parameter in self._read_service.list_parameters(model_version_id)
        }
        formula_refs = set(catalog.formula_by_ref())
        resolved: dict[WorkbookCellRef, ScalarValue] = {}
        payloads: list[dict[str, Any]] = []
        for override in overrides:
            if override.target_kind == "parameter":
                parameter = parameter_by_id.get(override.target_id or "")
                if parameter is None:
                    raise ValueError("Canonical parameter was not found in the model")
                if not parameter.source_sheet or not parameter.source_cell:
                    raise ValueError("Canonical parameter does not have a source cell")
                sheet_name = parameter.source_sheet
                cell_address = parameter.source_cell
            else:
                sheet_name = override.sheet_name or ""
                cell_address = override.cell_address or ""
            sheet_position = catalog.sheet_position(sheet_name)
            if sheet_position is None:
                raise ValueError("Override sheet was not found in the workbook")
            reference = WorkbookCellRef(
                catalog.workbook_version_id,
                sheet_name,
                sheet_position,
                cell_address,
            )
            if reference in formula_refs:
                raise ValueError("Formula cells cannot be overridden")
            if reference in resolved:
                raise ValueError("More than one override targets the same workbook cell")
            scalar = scalar_from_python(
                override.value,
                override.value_type,
                catalog.workbook_date_system,
            )
            if scalar.kind == "error":
                raise ValueError("Override value cannot be converted to a trusted scalar")
            resolved[reference] = scalar
            payloads.append(
                {
                    **override.to_payload(),
                    "sheet_name": reference.sheet_name,
                    "sheet_position": reference.sheet_position,
                    "cell_address": reference.cell_address,
                    "target_key": (
                        f"{reference.sheet_position}|{reference.sheet_name}|"
                        f"{reference.cell_address}"
                    ),
                    "typed_value": scalar.to_json(),
                }
            )
        payloads.sort(key=lambda item: str(item["target_key"]))
        return resolved, tuple(payloads)

    @staticmethod
    def _changed_cells(
        workbook_version_id: str,
        current: Sequence[Mapping[str, Any]],
        previous: Sequence[Mapping[str, Any]],
    ) -> tuple[WorkbookCellRef, ...]:
        current_by_key = {str(item["target_key"]): item for item in current}
        previous_by_key = {str(item["target_key"]): item for item in previous}
        changed: list[WorkbookCellRef] = []
        for key in sorted(set(current_by_key) | set(previous_by_key)):
            if current_by_key.get(key) == previous_by_key.get(key):
                continue
            item = current_by_key.get(key) or previous_by_key[key]
            changed.append(
                WorkbookCellRef(
                    workbook_version_id,
                    str(item["sheet_name"]),
                    int(item["sheet_position"]),
                    str(item["cell_address"]),
                )
            )
        return tuple(changed)

    @staticmethod
    def _prior_values_by_ref(
        workbook_version_id: str,
        prior: PersistedCalculationRun | None,
    ) -> dict[WorkbookCellRef, Any]:
        if prior is None:
            return {}
        return {
            WorkbookCellRef(
                workbook_version_id,
                value.sheet_name,
                value.sheet_position,
                value.cell_address,
            ): value
            for value in prior.values
        }

    @staticmethod
    def _run_values(
        run_id: str,
        prior_run_id: str | None,
        catalog: WorkbookCatalog,
        compilations: Sequence[FormulaCompilation],
        executions: Mapping[WorkbookCellRef, FormulaExecution],
        configuration: Phase2CalculationConfiguration,
    ) -> tuple[CalculationRunValueData, ...]:
        compilation_by_formula = {
            compilation.formula_cell_id: compilation
            for compilation in compilations
        }
        comparator = CachedValueComparator(configuration)
        rows: list[CalculationRunValueData] = []
        for reference, formula in sorted(
            catalog.formula_by_ref().items(),
            key=lambda item: _cell_sort_key(item[0]),
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
            compilation = compilation_by_formula[formula.id]
            rows.append(
                CalculationRunValueData(
                    id=str(
                        uuid.uuid5(
                            uuid.UUID(run_id),
                            f"calculation-value|{formula.id}",
                        )
                    ),
                    calculation_run_id=run_id,
                    formula_cell_id=formula.id,
                    expression_id=compilation.expression_id,
                    execution_status=execution.status,
                    value=execution.value,
                    engine_error_code=(
                        execution.error_code
                        if execution.status == "execution_error"
                        else None
                    ),
                    reused_from_run_id=(
                        prior_run_id if execution.status == "reused" else None
                    ),
                    direct_input_trace=execution.direct_input_trace,
                    validation_status=comparison.validation_status,
                    warnings=execution.warnings,
                )
            )
        return tuple(rows)

    @staticmethod
    def _summary(
        compiled: _CompiledWorkbook,
        rows: Sequence[CalculationRunValueData],
        grouped_rule_count: int,
        *,
        dirty_count: int,
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        supported = sum(
            item.support_status == "supported" for item in compiled.compilations
        )
        unsupported = len(compiled.compilations) - supported
        calculated = sum(item.execution_status == "executed" for item in rows)
        reused = sum(item.execution_status == "reused" for item in rows)
        cycles = sum(item.execution_status == "cycle" for item in rows)
        blocked = sum(
            item.execution_status == "blocked_by_dependency" for item in rows
        )
        errors = sum(item.execution_status == "execution_error" for item in rows)
        summary = {
            "formula_cells_total": len(compiled.catalog.formulas),
            "formula_cells_supported": supported,
            "unsupported_formula_cells": unsupported,
            "calculated_formula_cells": calculated,
            "reused_formula_cells": reused,
            "dirty_formula_cells": dirty_count,
            "cycle_formula_cells": cycles,
            "blocked_formula_cells": blocked,
            "execution_error_cells": errors,
            "grouped_calculation_rules": grouped_rule_count,
            "graph_nodes": compiled.graph.node_count,
            "graph_edges": compiled.graph.edge_count,
        }
        warnings: list[str] = []
        if unsupported:
            warnings.append("unsupported_formula_cells")
        if cycles:
            warnings.append("cycles_detected")
        if blocked:
            warnings.append("blocked_by_dependency")
        if errors:
            warnings.append("execution_errors")
        return summary, tuple(warnings)

    @staticmethod
    def _compilation_result(
        compiled: _CompiledWorkbook,
        configuration: Phase2CalculationConfiguration,
    ) -> WorkbookCompilationResult:
        supported = sum(
            item.support_status == "supported" for item in compiled.compilations
        )
        return WorkbookCompilationResult(
            workbook_version_id=compiled.catalog.workbook_version_id,
            graph_version_id=compiled.graph.id,
            ir_version=configuration.ir_version,
            compiler_version=configuration.compiler_version,
            function_registry_version=configuration.function_registry_version,
            semantics_profile=configuration.semantics_profile,
            formula_cells_total=len(compiled.catalog.formulas),
            formula_cells_supported=supported,
            formula_cells_unsupported=len(compiled.compilations) - supported,
            graph_nodes=compiled.graph.node_count,
            graph_edges=compiled.graph.edge_count,
        )

    @staticmethod
    def _result_from_persisted(
        persisted: PersistedCalculationRun,
        configuration: Phase2CalculationConfiguration,
    ) -> CalculationRunResult:
        cells = tuple(
            CalculationCellResult(
                formula_cell_id=value.formula_cell_id,
                expression_id=value.expression_id,
                sheet_name=value.sheet_name,
                sheet_position=value.sheet_position,
                cell_address=value.cell_address,
                status=value.execution_status,
                value=value.value,
                engine_error_code=value.engine_error_code,
                reused_from_run_id=value.reused_from_run_id,
                validation_status=value.validation_status,
                warnings=value.warnings,
            )
            for value in persisted.values
        )
        return CalculationRunResult(
            calculation_run_id=persisted.calculation_run_id,
            model_version_id=persisted.model_version_id,
            graph_version_id=persisted.graph_version_id,
            base_run_id=persisted.base_run_id,
            ir_version=configuration.ir_version,
            compiler_version=configuration.compiler_version,
            engine_version=persisted.engine_version,
            function_registry_version=persisted.function_registry_version,
            semantics_profile=persisted.semantics_profile,
            status=persisted.status,
            summary=persisted.summary,
            warnings=persisted.warnings,
            cells=cells,
        )


def _cell_sort_key(reference: WorkbookCellRef) -> tuple[int, int, int]:
    row, column = coordinate_to_tuple(reference.cell_address)
    return reference.sheet_position, row, column
