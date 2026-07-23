"""Persistence adapter for immutable Phase 2 graph, group, and run artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .evaluator import ScalarValue
from .models import ExecutableFormulaRule, WorkbookFormulaCellRecord, utcnow
from .phase2_graph import CalculationGraphVersion
from .phase2_grouping import GroupedCalculationRule
from .phase2_models import (
    CalculationGraphComponentRecord,
    CalculationGraphVersionRecord,
    CalculationRuleMemberRecord,
    CalculationRunRecord,
    CalculationRunValueRecord,
    GroupedCalculationRuleRecord,
)
from .phase2_types import Phase2CalculationConfiguration, canonical_hash
from .types import WorkbookCellRef


@dataclass(frozen=True)
class CalculationRunValueData:
    id: str
    calculation_run_id: str
    formula_cell_id: str
    expression_id: str
    execution_status: str
    value: ScalarValue | None
    engine_error_code: str | None
    reused_from_run_id: str | None
    direct_input_trace: tuple[dict[str, Any], ...]
    validation_status: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class PersistedCalculationRunValue:
    id: str
    formula_cell_id: str
    expression_id: str
    sheet_name: str
    sheet_position: int
    cell_address: str
    support_status: str
    execution_status: str
    value: ScalarValue | None
    engine_error_code: str | None
    reused_from_run_id: str | None
    direct_input_trace: tuple[dict[str, Any], ...]
    validation_status: str
    warnings: tuple[str, ...]

    @property
    def display(self) -> str:
        return f"{self.sheet_name}!{self.cell_address}"


@dataclass(frozen=True)
class PersistedCalculationRun:
    calculation_run_id: str
    model_version_id: str
    graph_version_id: str
    base_run_id: str | None
    engine_version: str
    function_registry_version: str
    semantics_profile: str
    normalized_override_hash: str
    run_policy_hash: str
    overrides: tuple[Mapping[str, Any], ...]
    run_policy: Mapping[str, Any]
    status: str
    summary: Mapping[str, Any]
    warnings: tuple[str, ...]
    values: tuple[PersistedCalculationRunValue, ...]

    @property
    def values_by_address(self) -> dict[str, PersistedCalculationRunValue]:
        return {value.display: value for value in self.values}


@dataclass(frozen=True)
class PersistedCalculationGraphMetadata:
    graph_version_id: str
    workbook_version_id: str
    compiler_version: str
    ir_version: str
    function_registry_version: str
    semantics_profile: str
    compiler_manifest_hash: str
    content_fingerprint: str
    node_count: int
    edge_count: int


@dataclass(frozen=True)
class PersistedCalculationRunBundle:
    run: PersistedCalculationRun
    graph: PersistedCalculationGraphMetadata


class Phase2CalculationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_graph(
        self,
        graph: CalculationGraphVersion,
        configuration: Phase2CalculationConfiguration,
    ) -> CalculationGraphVersionRecord:
        existing = self._session.get(CalculationGraphVersionRecord, graph.id)
        if existing is not None:
            if (
                existing.workbook_version_id != graph.workbook_version_id
                or existing.compiler_manifest_hash != graph.compiler_manifest_hash
                or existing.content_fingerprint != graph.content_fingerprint
                or existing.node_count != graph.node_count
                or existing.edge_count != graph.edge_count
            ):
                raise ValueError("Persisted calculation graph is not immutable")
            return existing

        row = CalculationGraphVersionRecord(
            id=graph.id,
            workbook_version_id=graph.workbook_version_id,
            compiler_version=configuration.compiler_version,
            ir_version=configuration.ir_version,
            function_registry_version=configuration.function_registry_version,
            semantics_profile=configuration.semantics_profile,
            compiler_manifest_hash=graph.compiler_manifest_hash,
            content_fingerprint=graph.content_fingerprint,
            node_count=graph.node_count,
            edge_count=graph.edge_count,
            topological_layers_json=[
                [_cell_payload(member) for member in members]
                for members in graph.topological_layers
            ],
            volatile_nodes_json=[],
        )
        self._session.add(row)
        self._session.flush()
        for component in graph.components:
            self._session.add(
                CalculationGraphComponentRecord(
                    id=component.id,
                    graph_version_id=graph.id,
                    ordinal=component.ordinal,
                    classification=component.classification,
                    member_count=len(component.members),
                    member_formula_cells_json=[
                        _cell_payload(member) for member in component.members
                    ],
                    topological_layer=component.topological_layer,
                    iteration_enabled=component.iteration_enabled,
                )
            )
        self._session.flush()
        return row

    def save_groups(
        self,
        graph_version_id: str,
        groups: Sequence[GroupedCalculationRule],
    ) -> None:
        if self._session.get(CalculationGraphVersionRecord, graph_version_id) is None:
            raise ValueError("Calculation graph must exist before grouped rules")
        for group in groups:
            existing = self._session.get(GroupedCalculationRuleRecord, group.id)
            if existing is not None:
                if (
                    existing.model_version_id != group.model_version_id
                    or existing.graph_version_id != graph_version_id
                    or existing.group_fingerprint != group.group_fingerprint
                    or existing.normalized_expression != group.normalized_expression
                ):
                    raise ValueError("Persisted grouped calculation rule is not immutable")
                continue
            self._session.add(
                GroupedCalculationRuleRecord(
                    id=group.id,
                    model_version_id=group.model_version_id,
                    graph_version_id=graph_version_id,
                    grouping_profile=group.grouping_profile,
                    group_fingerprint=group.group_fingerprint,
                    label=group.label,
                    normalized_expression=group.normalized_expression,
                    orientation=group.orientation,
                    exceptions_json=list(group.exceptions),
                    confidence=group.confidence,
                    approval_status=group.approval_status,
                    compiler_version=group.compiler_version,
                    semantics_profile=group.semantics_profile,
                )
            )
            self._session.flush()
            for member in group.members:
                self._session.add(
                    CalculationRuleMemberRecord(
                        id=member.id,
                        grouped_rule_id=group.id,
                        formula_cell_id=member.formula_cell_id,
                        expression_id=member.expression_id,
                        ordinal=member.ordinal,
                        period_offset=member.period_offset,
                        sheet_name=member.sheet_name,
                        cell_address=member.cell_address,
                    )
                )
        self._session.flush()

    def find_matching_graph(
        self,
        workbook_version_id: str,
        configuration: Phase2CalculationConfiguration,
    ) -> PersistedCalculationGraphMetadata | None:
        graph_id = self._session.scalar(
            select(CalculationGraphVersionRecord.id)
            .where(
                CalculationGraphVersionRecord.workbook_version_id
                == workbook_version_id,
                CalculationGraphVersionRecord.compiler_version
                == configuration.compiler_version,
                CalculationGraphVersionRecord.ir_version == configuration.ir_version,
                CalculationGraphVersionRecord.function_registry_version
                == configuration.function_registry_version,
                CalculationGraphVersionRecord.semantics_profile
                == configuration.semantics_profile,
            )
            .order_by(
                CalculationGraphVersionRecord.created_at.desc(),
                CalculationGraphVersionRecord.id.desc(),
            )
            .limit(1)
        )
        return self.load_graph_metadata(graph_id) if graph_id is not None else None

    def load_graph_metadata(
        self,
        graph_version_id: str,
    ) -> PersistedCalculationGraphMetadata | None:
        row = self._session.get(CalculationGraphVersionRecord, graph_version_id)
        if row is None:
            return None
        return PersistedCalculationGraphMetadata(
            graph_version_id=row.id,
            workbook_version_id=row.workbook_version_id,
            compiler_version=row.compiler_version,
            ir_version=row.ir_version,
            function_registry_version=row.function_registry_version,
            semantics_profile=row.semantics_profile,
            compiler_manifest_hash=row.compiler_manifest_hash,
            content_fingerprint=row.content_fingerprint,
            node_count=row.node_count,
            edge_count=row.edge_count,
        )

    def is_current_graph(
        self,
        workbook_version_id: str,
        graph_version_id: str,
        configuration: Phase2CalculationConfiguration,
    ) -> bool:
        current = self.find_matching_graph(workbook_version_id, configuration)
        return current is not None and current.graph_version_id == graph_version_id

    def load_run_bundle(
        self,
        run_id: str,
    ) -> PersistedCalculationRunBundle | None:
        if self._session.get(CalculationRunRecord, run_id) is None:
            return None
        run = self.load_run(run_id)
        graph = self.load_graph_metadata(run.graph_version_id)
        if graph is None:
            raise ValueError("Calculation run graph metadata was not found")
        return PersistedCalculationRunBundle(run=run, graph=graph)

    def start_run(
        self,
        run_id: str,
        model_version_id: str,
        graph_version_id: str,
        configuration: Phase2CalculationConfiguration,
        *,
        normalized_override_hash: str,
        run_policy_hash: str,
        overrides: Sequence[Mapping[str, Any]],
        run_policy: Mapping[str, Any],
        base_run_id: str | None = None,
    ) -> CalculationRunRecord:
        existing = self._session.get(CalculationRunRecord, run_id)
        if existing is not None:
            expected = (
                model_version_id,
                graph_version_id,
                configuration.function_registry_version,
                normalized_override_hash,
                run_policy_hash,
            )
            actual = (
                existing.model_version_id,
                existing.graph_version_id,
                existing.function_registry_version,
                existing.normalized_override_hash,
                existing.run_policy_hash,
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

        row = CalculationRunRecord(
            id=run_id,
            model_version_id=model_version_id,
            graph_version_id=graph_version_id,
            base_run_id=base_run_id,
            engine_version=configuration.engine_version,
            function_registry_version=configuration.function_registry_version,
            semantics_profile=configuration.semantics_profile,
            normalized_override_hash=normalized_override_hash,
            run_policy_hash=run_policy_hash,
            overrides_json=[dict(item) for item in overrides],
            run_policy_json=dict(run_policy),
            status="running",
            started_at=utcnow(),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def replace_run_values(
        self,
        run_id: str,
        values: Sequence[CalculationRunValueData],
    ) -> None:
        if self._session.get(CalculationRunRecord, run_id) is None:
            raise ValueError("Calculation run must exist before values are persisted")
        self._session.execute(
            delete(CalculationRunValueRecord).where(
                CalculationRunValueRecord.calculation_run_id == run_id
            )
        )
        self._session.flush()
        for value in values:
            if value.calculation_run_id != run_id:
                raise ValueError("Calculation value belongs to another run")
            payload = value.value.to_json() if value.value is not None else None
            self._session.add(
                CalculationRunValueRecord(
                    id=value.id,
                    calculation_run_id=run_id,
                    formula_cell_id=value.formula_cell_id,
                    expression_id=value.expression_id,
                    execution_status=value.execution_status,
                    value_type=value.value.kind if value.value is not None else None,
                    value_json=payload,
                    excel_error_code=(
                        value.value.error_code
                        if value.value is not None and value.value.kind == "error"
                        else None
                    ),
                    engine_error_code=value.engine_error_code,
                    reused_from_run_id=value.reused_from_run_id,
                    direct_input_trace_json=list(value.direct_input_trace),
                    validation_status=value.validation_status,
                    warnings_json=list(value.warnings),
                )
            )
        self._session.flush()

    def complete_run(
        self,
        run_id: str,
        *,
        status: str,
        summary: Mapping[str, Any],
        warnings: Sequence[str],
    ) -> None:
        if status not in {"completed", "completed_with_warning"}:
            raise ValueError("Completed Phase 2 calculation run has invalid status")
        row = self._session.get(CalculationRunRecord, run_id)
        if row is None:
            raise ValueError("Calculation run was not found")
        row.status = status
        row.summary_json = dict(summary)
        row.warnings_json = list(warnings)
        row.error_code = None
        row.error_message = None
        row.completed_at = utcnow()
        self._session.flush()

    def mark_failed(
        self,
        run_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        row = self._session.get(CalculationRunRecord, run_id)
        if row is None:
            raise ValueError("Calculation run was not found")
        row.status = "failed"
        row.error_code = error_code[:100]
        row.error_message = error_message[:1000]
        row.completed_at = utcnow()
        self._session.flush()

    def load_completed_run(self, run_id: str) -> PersistedCalculationRun | None:
        row = self._session.get(CalculationRunRecord, run_id)
        if row is None or row.status not in {"completed", "completed_with_warning"}:
            return None
        return self.load_run(run_id)

    def find_latest_compatible_run(
        self,
        model_version_id: str,
        graph_version_id: str,
        configuration: Phase2CalculationConfiguration,
        *,
        exclude_run_id: str | None = None,
    ) -> PersistedCalculationRun | None:
        statement = (
            select(CalculationRunRecord.id)
            .where(
                CalculationRunRecord.model_version_id == model_version_id,
                CalculationRunRecord.graph_version_id == graph_version_id,
                CalculationRunRecord.engine_version == configuration.engine_version,
                CalculationRunRecord.function_registry_version
                == configuration.function_registry_version,
                CalculationRunRecord.semantics_profile
                == configuration.semantics_profile,
                CalculationRunRecord.status.in_(
                    ("completed", "completed_with_warning")
                ),
            )
            .order_by(
                CalculationRunRecord.completed_at.desc(),
                CalculationRunRecord.created_at.desc(),
                CalculationRunRecord.id.desc(),
            )
        )
        if exclude_run_id is not None:
            statement = statement.where(CalculationRunRecord.id != exclude_run_id)
        run_id = self._session.scalar(statement.limit(1))
        return self.load_run(run_id) if run_id is not None else None

    def find_completed_zero_override_run(
        self,
        model_version_id: str,
        graph_version_id: str,
        *,
        engine_version: str,
        function_registry_version: str,
        semantics_profile: str,
        run_policy_hash: str,
    ) -> PersistedCalculationRun | None:
        run_id = self._session.scalar(
            select(CalculationRunRecord.id)
            .where(
                CalculationRunRecord.model_version_id == model_version_id,
                CalculationRunRecord.graph_version_id == graph_version_id,
                CalculationRunRecord.engine_version == engine_version,
                CalculationRunRecord.function_registry_version
                == function_registry_version,
                CalculationRunRecord.semantics_profile == semantics_profile,
                CalculationRunRecord.normalized_override_hash
                == canonical_hash([]),
                CalculationRunRecord.run_policy_hash == run_policy_hash,
                CalculationRunRecord.status.in_(
                    ("completed", "completed_with_warning")
                ),
            )
            .order_by(
                CalculationRunRecord.completed_at.desc(),
                CalculationRunRecord.created_at.desc(),
                CalculationRunRecord.id.desc(),
            )
            .limit(1)
        )
        if run_id is None:
            return None
        run = self.load_run(run_id)
        return None if run.overrides else run

    def load_run(self, run_id: str) -> PersistedCalculationRun:
        row = self._session.get(CalculationRunRecord, run_id)
        if row is None:
            raise ValueError("Calculation run was not found")
        value_rows = self._session.execute(
            select(
                CalculationRunValueRecord,
                WorkbookFormulaCellRecord,
                ExecutableFormulaRule,
            )
            .join(
                WorkbookFormulaCellRecord,
                WorkbookFormulaCellRecord.id
                == CalculationRunValueRecord.formula_cell_id,
            )
            .join(
                ExecutableFormulaRule,
                ExecutableFormulaRule.id
                == CalculationRunValueRecord.expression_id,
            )
            .where(CalculationRunValueRecord.calculation_run_id == run_id)
            .order_by(
                WorkbookFormulaCellRecord.sheet_position,
                WorkbookFormulaCellRecord.row_index,
                WorkbookFormulaCellRecord.column_index,
            )
        ).all()
        values = tuple(
            PersistedCalculationRunValue(
                id=value.id,
                formula_cell_id=value.formula_cell_id,
                expression_id=value.expression_id,
                sheet_name=formula.sheet_name,
                sheet_position=formula.sheet_position,
                cell_address=formula.cell_address,
                support_status=rule.support_status,
                execution_status=value.execution_status,
                value=ScalarValue.from_json(value.value_json),
                engine_error_code=value.engine_error_code,
                reused_from_run_id=value.reused_from_run_id,
                direct_input_trace=tuple(value.direct_input_trace_json or ()),
                validation_status=value.validation_status,
                warnings=tuple(value.warnings_json or ()),
            )
            for value, formula, rule in value_rows
        )
        return PersistedCalculationRun(
            calculation_run_id=row.id,
            model_version_id=row.model_version_id,
            graph_version_id=row.graph_version_id,
            base_run_id=row.base_run_id,
            engine_version=row.engine_version,
            function_registry_version=row.function_registry_version,
            semantics_profile=row.semantics_profile,
            normalized_override_hash=row.normalized_override_hash,
            run_policy_hash=row.run_policy_hash,
            overrides=tuple(dict(item) for item in (row.overrides_json or ())),
            run_policy=dict(row.run_policy_json or {}),
            status=row.status,
            summary=dict(row.summary_json or {}),
            warnings=tuple(row.warnings_json or ()),
            values=values,
        )


def _cell_payload(reference: WorkbookCellRef) -> dict[str, object]:
    return {
        "sheet_name": reference.sheet_name,
        "sheet_position": reference.sheet_position,
        "cell_address": reference.cell_address,
    }
