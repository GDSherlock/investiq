"""Persistence adapter for immutable compilations and model-scoped run output."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping, Sequence

from openpyxl.utils.cell import coordinate_to_tuple
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..model_extraction_types import json_safe
from .comparison import CachedValueComparison
from .evaluator import FormulaExecution, ScalarValue
from .models import (
    CalculationRuleExtraction,
    ExecutableFormulaRule,
    FormulaCanonicalMapping,
    FormulaExecutionResultRecord,
    FormulaReferenceRecord,
    WorkbookFormulaCellRecord,
    utcnow,
)
from .types import (
    CalculationRuleExtractionConfiguration,
    FormulaCompilation,
    FormulaReference,
    WorkbookCatalog,
    WorkbookCellRef,
    WorkbookFormulaCell,
)


@dataclass(frozen=True)
class FormulaCanonicalMappingData:
    id: str
    calculation_rule_extraction_id: str
    formula_cell_id: str
    reference_id: str | None
    mapping_role: str
    mapping_status: str
    entity_kind: str | None
    entity_id: str | None
    financial_series_value_id: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class FormulaExecutionPersistenceData:
    id: str
    calculation_rule_extraction_id: str
    formula_cell_id: str
    expression_id: str
    execution: FormulaExecution
    comparison: CachedValueComparison


@dataclass(frozen=True)
class CalculationCellResult:
    formula_cell: WorkbookFormulaCell
    compilation: FormulaCompilation
    mappings: tuple[FormulaCanonicalMappingData, ...]
    execution: FormulaExecution
    comparison: CachedValueComparison


@dataclass(frozen=True)
class CalculationRuleExtractionResult:
    calculation_rule_extraction_id: str
    model_version_id: str
    workbook_version_id: str
    ir_version: str
    compiler_version: str
    engine_version: str
    function_registry_version: str
    semantics_profile: str
    status: str
    summary: Mapping[str, Any]
    warnings: tuple[str, ...]
    cells: tuple[CalculationCellResult, ...]

    @property
    def cells_by_address(self) -> dict[str, CalculationCellResult]:
        return {
            cell.formula_cell.ref.display: cell
            for cell in self.cells
        }

    @property
    def metrics(self) -> Mapping[str, Any]:
        metrics = self.summary.get("metrics", {})
        return metrics if isinstance(metrics, Mapping) else {}


class CalculationRuleRepository:
    def __init__(self, session: Session):
        self._session = session

    def start_run(
        self,
        extraction_id: str,
        model_version_id: str,
        workbook_version_id: str,
        configuration: CalculationRuleExtractionConfiguration,
    ) -> CalculationRuleExtraction:
        existing = self._session.get(CalculationRuleExtraction, extraction_id)
        if existing is not None:
            expected = (
                model_version_id,
                workbook_version_id,
                configuration.compiler_version,
                configuration.engine_version,
                configuration.semantics_profile,
                configuration.configuration_hash,
            )
            actual = (
                existing.model_version_id,
                existing.workbook_version_id,
                existing.compiler_version,
                existing.engine_version,
                existing.semantics_profile,
                existing.configuration_hash,
            )
            if actual != expected:
                raise ValueError("Existing calculation run identity does not match request")
            if existing.status == "failed":
                existing.status = "running"
                existing.error_code = None
                existing.error_message = None
                existing.summary_json = None
                existing.warnings_json = None
                existing.started_at = utcnow()
                existing.completed_at = None
            self._session.flush()
            return existing

        run = CalculationRuleExtraction(
            id=extraction_id,
            workbook_version_id=workbook_version_id,
            model_version_id=model_version_id,
            inventory_version=configuration.inventory_version,
            compiler_version=configuration.compiler_version,
            ir_version=configuration.ir_version,
            engine_version=configuration.engine_version,
            function_registry_version=configuration.function_registry_version,
            semantics_profile=configuration.semantics_profile,
            configuration_hash=configuration.configuration_hash,
            status="running",
            started_at=utcnow(),
        )
        self._session.add(run)
        self._session.flush()
        return run

    def load_completed_result(
        self,
        extraction_id: str,
    ) -> CalculationRuleExtractionResult | None:
        run = self._session.get(CalculationRuleExtraction, extraction_id)
        if run is None or run.status not in {"completed", "completed_with_warning"}:
            return None
        return self.load_result(extraction_id)

    def save_compilation(
        self,
        catalog: WorkbookCatalog,
        compilations: Sequence[FormulaCompilation],
        configuration: CalculationRuleExtractionConfiguration,
    ) -> None:
        compilation_by_cell = {
            compilation.formula_cell_id: compilation for compilation in compilations
        }
        if set(compilation_by_cell) != {formula.id for formula in catalog.formulas}:
            raise ValueError("Compilation rows must cover the workbook formula inventory")

        for formula in catalog.formulas:
            existing = self._session.get(WorkbookFormulaCellRecord, formula.id)
            if existing is not None:
                if (
                    existing.workbook_version_id != catalog.workbook_version_id
                    or existing.formula_sha256 != formula.formula_sha256
                    or existing.exact_formula != formula.exact_formula
                ):
                    raise ValueError("Persisted formula inventory is not immutable")
                continue
            row_index, column_index = coordinate_to_tuple(formula.ref.cell_address)
            self._session.add(
                WorkbookFormulaCellRecord(
                    id=formula.id,
                    workbook_version_id=catalog.workbook_version_id,
                    sheet_name=formula.ref.sheet_name,
                    sheet_position=formula.ref.sheet_position,
                    sheet_state=formula.sheet_state,
                    row_index=row_index,
                    column_index=column_index,
                    cell_address=formula.ref.cell_address,
                    exact_formula=formula.exact_formula,
                    formula_sha256=formula.formula_sha256,
                    formula_kind=formula.formula_kind,
                    special_range=formula.special_range,
                    special_metadata_json=json_safe(formula.special_metadata),
                    cached_value_json=json_safe(formula.cached_value),
                    cached_value_type=formula.cached_value_type,
                    cache_status=formula.cache_status,
                    cache_freshness=formula.cache_freshness,
                    number_format=formula.number_format,
                    data_type=formula.data_type,
                    inventory_version=configuration.inventory_version,
                )
            )
        self._session.flush()

        for compilation in compilations:
            existing = self._session.get(ExecutableFormulaRule, compilation.expression_id)
            if existing is not None:
                if (
                    existing.formula_cell_id != compilation.formula_cell_id
                    or existing.formula_sha256 != compilation.formula_sha256
                    or existing.ir_json != compilation.ir_json
                    or existing.support_status != compilation.support_status
                ):
                    raise ValueError("Persisted formula compilation is not immutable")
                continue
            signature_hash = (
                sha256(compilation.normalized_signature.encode("utf-8")).hexdigest()
                if compilation.normalized_signature is not None
                else None
            )
            self._session.add(
                ExecutableFormulaRule(
                    id=compilation.expression_id,
                    formula_cell_id=compilation.formula_cell_id,
                    ir_version=compilation.ir_version,
                    compiler_version=compilation.compiler_version,
                    semantics_profile=compilation.semantics_profile,
                    formula_sha256=compilation.formula_sha256,
                    normalized_signature=compilation.normalized_signature,
                    normalized_signature_hash=signature_hash,
                    parse_status=compilation.parse_status,
                    support_status=compilation.support_status,
                    ir_json=compilation.ir_json,
                    unsupported_constructs_json=list(
                        compilation.unsupported_constructs
                    ),
                    warnings_json=list(compilation.warnings),
                )
            )
        self._session.flush()

        for compilation in compilations:
            for reference in compilation.references:
                existing = self._session.get(FormulaReferenceRecord, reference.id)
                if existing is not None:
                    if (
                        existing.executable_formula_rule_id != reference.expression_id
                        or existing.source_token != reference.source_token
                        or existing.resolution_status != reference.resolution_status
                    ):
                        raise ValueError("Persisted formula reference is not immutable")
                    continue
                self._session.add(
                    FormulaReferenceRecord(
                        id=reference.id,
                        executable_formula_rule_id=reference.expression_id,
                        ordinal=reference.ordinal,
                        source_token=reference.source_token,
                        source_span_start=reference.source_span_start,
                        source_span_end=reference.source_span_end,
                        reference_kind=reference.reference_kind,
                        target_classification=reference.target_classification,
                        target_sheet_name=reference.target_sheet_name,
                        target_sheet_position=reference.target_sheet_position,
                        start_cell_address=reference.start_cell_address,
                        end_cell_address=reference.end_cell_address,
                        start_column_absolute=reference.start_column_absolute,
                        start_row_absolute=reference.start_row_absolute,
                        end_column_absolute=reference.end_column_absolute,
                        end_row_absolute=reference.end_row_absolute,
                        range_rows=reference.range_rows,
                        range_columns=reference.range_columns,
                        resolution_status=reference.resolution_status,
                        warning_code=reference.warning_code,
                    )
                )
        self._session.flush()

    def replace_outputs(
        self,
        extraction_id: str,
        mappings: Sequence[FormulaCanonicalMappingData],
        results: Sequence[FormulaExecutionPersistenceData],
        configuration: CalculationRuleExtractionConfiguration,
    ) -> None:
        if self._session.get(CalculationRuleExtraction, extraction_id) is None:
            raise ValueError("Calculation run must exist before outputs are persisted")
        self._session.execute(
            delete(FormulaCanonicalMapping).where(
                FormulaCanonicalMapping.calculation_rule_extraction_id == extraction_id
            )
        )
        self._session.execute(
            delete(FormulaExecutionResultRecord).where(
                FormulaExecutionResultRecord.calculation_rule_extraction_id
                == extraction_id
            )
        )
        self._session.flush()
        for mapping in mappings:
            if mapping.calculation_rule_extraction_id != extraction_id:
                raise ValueError("Canonical mapping belongs to another extraction")
            self._session.add(
                FormulaCanonicalMapping(
                    id=mapping.id,
                    calculation_rule_extraction_id=extraction_id,
                    formula_cell_id=mapping.formula_cell_id,
                    reference_id=mapping.reference_id,
                    mapping_role=mapping.mapping_role,
                    mapping_status=mapping.mapping_status,
                    entity_kind=mapping.entity_kind,
                    entity_id=mapping.entity_id,
                    financial_series_value_id=mapping.financial_series_value_id,
                    warnings_json=list(mapping.warnings),
                )
            )
        for result in results:
            if result.calculation_rule_extraction_id != extraction_id:
                raise ValueError("Execution result belongs to another extraction")
            calculated_payload = (
                result.execution.value.to_json()
                if result.execution.value is not None
                else None
            )
            cached_payload = (
                result.comparison.cached_value.to_json()
                if result.comparison.cached_value is not None
                else None
            )
            self._session.add(
                FormulaExecutionResultRecord(
                    id=result.id,
                    calculation_rule_extraction_id=extraction_id,
                    formula_cell_id=result.formula_cell_id,
                    expression_id=result.expression_id,
                    execution_status=result.execution.status,
                    calculated_value_type=(
                        result.execution.value.kind
                        if result.execution.value is not None
                        else None
                    ),
                    calculated_value_json=calculated_payload,
                    excel_error_code=(
                        result.execution.value.error_code
                        if result.execution.value is not None
                        and result.execution.value.kind == "error"
                        else None
                    ),
                    engine_error_code=None,
                    direct_input_trace_json=list(
                        result.execution.direct_input_trace
                    ),
                    engine_version=configuration.engine_version,
                    semantics_profile=configuration.semantics_profile,
                    cached_value_type=(
                        result.comparison.cached_value.kind
                        if result.comparison.cached_value is not None
                        else None
                    ),
                    cached_value_json=cached_payload,
                    absolute_error=result.comparison.absolute_error,
                    relative_error=result.comparison.relative_error,
                    validation_status=result.comparison.validation_status,
                    cached_value_freshness=(
                        result.comparison.cached_value_freshness
                    ),
                    warnings_json=list(result.execution.warnings),
                    started_at=utcnow(),
                    completed_at=utcnow(),
                )
            )
        self._session.flush()

    def complete_run(
        self,
        extraction_id: str,
        *,
        status: str,
        summary: Mapping[str, Any],
        warnings: Sequence[str],
    ) -> None:
        if status not in {"completed", "completed_with_warning"}:
            raise ValueError("Completed calculation run has invalid status")
        run = self._session.get(CalculationRuleExtraction, extraction_id)
        if run is None:
            raise ValueError("Calculation run was not found")
        run.status = status
        run.summary_json = dict(summary)
        run.warnings_json = list(warnings)
        run.error_code = None
        run.error_message = None
        run.completed_at = utcnow()
        self._session.flush()

    def mark_failed(
        self,
        extraction_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        run = self._session.get(CalculationRuleExtraction, extraction_id)
        if run is None:
            raise ValueError("Calculation run was not found")
        run.status = "failed"
        run.error_code = error_code[:100]
        run.error_message = error_message[:1000]
        run.completed_at = utcnow()
        self._session.flush()

    def load_result(self, extraction_id: str) -> CalculationRuleExtractionResult:
        run = self._session.get(CalculationRuleExtraction, extraction_id)
        if run is None:
            raise ValueError("Calculation run was not found")
        formula_rows = self._session.scalars(
            select(WorkbookFormulaCellRecord)
            .where(
                WorkbookFormulaCellRecord.workbook_version_id
                == run.workbook_version_id
            )
            .order_by(
                WorkbookFormulaCellRecord.sheet_position,
                WorkbookFormulaCellRecord.row_index,
                WorkbookFormulaCellRecord.column_index,
            )
        ).all()
        formula_ids = [row.id for row in formula_rows]
        rule_rows = self._session.scalars(
            select(ExecutableFormulaRule).where(
                ExecutableFormulaRule.formula_cell_id.in_(formula_ids),
                ExecutableFormulaRule.ir_version == run.ir_version,
                ExecutableFormulaRule.compiler_version == run.compiler_version,
                ExecutableFormulaRule.semantics_profile == run.semantics_profile,
            )
        ).all()
        rule_by_cell = {row.formula_cell_id: row for row in rule_rows}
        rule_ids = [row.id for row in rule_rows]
        reference_rows = self._session.scalars(
            select(FormulaReferenceRecord)
            .where(FormulaReferenceRecord.executable_formula_rule_id.in_(rule_ids))
            .order_by(
                FormulaReferenceRecord.executable_formula_rule_id,
                FormulaReferenceRecord.ordinal,
            )
        ).all()
        references_by_rule: dict[str, list[FormulaReferenceRecord]] = {}
        for row in reference_rows:
            references_by_rule.setdefault(row.executable_formula_rule_id, []).append(row)
        mapping_rows = self._session.scalars(
            select(FormulaCanonicalMapping)
            .where(
                FormulaCanonicalMapping.calculation_rule_extraction_id
                == extraction_id
            )
            .order_by(
                FormulaCanonicalMapping.formula_cell_id,
                FormulaCanonicalMapping.mapping_role.desc(),
                FormulaCanonicalMapping.reference_id,
            )
        ).all()
        mappings_by_cell: dict[str, list[FormulaCanonicalMappingData]] = {}
        for row in mapping_rows:
            mappings_by_cell.setdefault(row.formula_cell_id, []).append(
                self._mapping_data(row)
            )
        result_rows = self._session.scalars(
            select(FormulaExecutionResultRecord).where(
                FormulaExecutionResultRecord.calculation_rule_extraction_id
                == extraction_id
            )
        ).all()
        result_by_cell = {row.formula_cell_id: row for row in result_rows}

        cells: list[CalculationCellResult] = []
        for formula_row in formula_rows:
            rule_row = rule_by_cell.get(formula_row.id)
            result_row = result_by_cell.get(formula_row.id)
            if rule_row is None or result_row is None:
                if run.status in {"completed", "completed_with_warning"}:
                    raise ValueError("Completed calculation run is missing cell output")
                continue
            formula_cell = self._formula_cell(formula_row)
            references = tuple(
                self._reference_data(row, formula_row.workbook_version_id, formula_row.id)
                for row in references_by_rule.get(rule_row.id, ())
            )
            compilation = FormulaCompilation(
                expression_id=rule_row.id,
                formula_cell_id=rule_row.formula_cell_id,
                ir_version=rule_row.ir_version,
                compiler_version=rule_row.compiler_version,
                semantics_profile=rule_row.semantics_profile,
                formula_sha256=rule_row.formula_sha256,
                normalized_signature=rule_row.normalized_signature,
                parse_status=rule_row.parse_status,
                support_status=rule_row.support_status,
                ir_json=rule_row.ir_json,
                references=references,
                unsupported_constructs=tuple(
                    rule_row.unsupported_constructs_json or ()
                ),
                warnings=tuple(rule_row.warnings_json or ()),
            )
            calculated = ScalarValue.from_json(result_row.calculated_value_json)
            cached = ScalarValue.from_json(result_row.cached_value_json)
            execution = FormulaExecution(
                status=result_row.execution_status,
                value=calculated,
                error_code=result_row.excel_error_code
                or result_row.engine_error_code,
                direct_input_trace=tuple(
                    result_row.direct_input_trace_json or ()
                ),
                warnings=tuple(result_row.warnings_json or ()),
            )
            comparison = CachedValueComparison(
                cached_value=cached,
                absolute_error=result_row.absolute_error,
                relative_error=result_row.relative_error,
                validation_status=result_row.validation_status,
                cached_value_freshness=result_row.cached_value_freshness,
            )
            cells.append(
                CalculationCellResult(
                    formula_cell=formula_cell,
                    compilation=compilation,
                    mappings=tuple(mappings_by_cell.get(formula_row.id, ())),
                    execution=execution,
                    comparison=comparison,
                )
            )
        return CalculationRuleExtractionResult(
            calculation_rule_extraction_id=run.id,
            model_version_id=run.model_version_id,
            workbook_version_id=run.workbook_version_id,
            ir_version=run.ir_version,
            compiler_version=run.compiler_version,
            engine_version=run.engine_version,
            function_registry_version=run.function_registry_version,
            semantics_profile=run.semantics_profile,
            status=run.status,
            summary=run.summary_json or {},
            warnings=tuple(run.warnings_json or ()),
            cells=tuple(cells),
        )

    @staticmethod
    def _formula_cell(row: WorkbookFormulaCellRecord) -> WorkbookFormulaCell:
        return WorkbookFormulaCell(
            id=row.id,
            ref=WorkbookCellRef(
                row.workbook_version_id,
                row.sheet_name,
                row.sheet_position,
                row.cell_address,
            ),
            exact_formula=row.exact_formula,
            formula_sha256=row.formula_sha256,
            formula_kind=row.formula_kind,
            cached_value=row.cached_value_json,
            cached_value_type=row.cached_value_type,
            cache_status=row.cache_status,
            cache_freshness=row.cache_freshness,
            number_format=row.number_format,
            data_type=row.data_type,
            sheet_state=row.sheet_state,
            special_range=row.special_range,
            special_metadata=row.special_metadata_json,
        )

    @staticmethod
    def _reference_data(
        row: FormulaReferenceRecord,
        workbook_version_id: str,
        formula_cell_id: str,
    ) -> FormulaReference:
        return FormulaReference(
            id=row.id,
            expression_id=row.executable_formula_rule_id,
            formula_cell_id=formula_cell_id,
            workbook_version_id=workbook_version_id,
            ordinal=row.ordinal,
            source_token=row.source_token,
            source_span_start=row.source_span_start,
            source_span_end=row.source_span_end,
            reference_kind=row.reference_kind,
            target_classification=row.target_classification,
            target_sheet_name=row.target_sheet_name,
            target_sheet_position=row.target_sheet_position,
            start_cell_address=row.start_cell_address,
            end_cell_address=row.end_cell_address,
            start_column_absolute=row.start_column_absolute,
            start_row_absolute=row.start_row_absolute,
            end_column_absolute=row.end_column_absolute,
            end_row_absolute=row.end_row_absolute,
            range_rows=row.range_rows,
            range_columns=row.range_columns,
            resolution_status=row.resolution_status,
            warning_code=row.warning_code,
        )

    @staticmethod
    def _mapping_data(row: FormulaCanonicalMapping) -> FormulaCanonicalMappingData:
        return FormulaCanonicalMappingData(
            id=row.id,
            calculation_rule_extraction_id=row.calculation_rule_extraction_id,
            formula_cell_id=row.formula_cell_id,
            reference_id=row.reference_id,
            mapping_role=row.mapping_role,
            mapping_status=row.mapping_status,
            entity_kind=row.entity_kind,
            entity_id=row.entity_id,
            financial_series_value_id=row.financial_series_value_id,
            warnings=tuple(row.warnings_json or ()),
        )
