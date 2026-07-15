"""Typed contracts and stable identities for calculation rule extraction."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
import hashlib
import json
import re
from typing import Any, Literal, Mapping
import uuid

from openpyxl.utils.cell import column_index_from_string

from .function_registry import FUNCTION_REGISTRY_VERSION


_A1_PATTERN = re.compile(r"^\$?([A-Za-z]{1,3})\$?([1-9][0-9]{0,6})$")
_MAX_EXCEL_COLUMN = 16_384
_MAX_EXCEL_ROW = 1_048_576


def normalize_a1(address: str) -> str:
    match = _A1_PATTERN.fullmatch(address.strip())
    if match is None:
        raise ValueError("Cell address must use bounded A1 notation")
    column_text, row_text = match.groups()
    column_index = column_index_from_string(column_text.upper())
    row_index = int(row_text)
    if column_index > _MAX_EXCEL_COLUMN or row_index > _MAX_EXCEL_ROW:
        raise ValueError("Cell address is outside Excel worksheet bounds")
    return f"{column_text.upper()}{row_index}"


@dataclass(frozen=True)
class CalculationRuleExtractionConfiguration:
    inventory_version: str = "formula-inventory-v1"
    ir_version: str = "calc-ir-v1"
    compiler_version: str = "formula-compiler-v1"
    engine_version: str = "calc-engine-v1"
    function_registry_version: str = "function-registry-v1"
    semantics_profile: str = "excel-subset-v1"
    max_formula_length: int = 8_192
    max_tokens: int = 2_048
    max_nodes: int = 2_048
    max_depth: int = 128
    max_arguments: int = 255
    max_range_cells: int = 10_000
    max_formula_count: int = 100_000
    max_total_edges: int = 1_000_000
    max_trace_inputs: int = 256
    absolute_tolerance: float = 1e-9
    relative_tolerance: float = 1e-9

    def __post_init__(self) -> None:
        expected_versions = {
            "inventory_version": "formula-inventory-v1",
            "ir_version": "calc-ir-v1",
            "compiler_version": "formula-compiler-v1",
            "engine_version": "calc-engine-v1",
            "function_registry_version": FUNCTION_REGISTRY_VERSION,
            "semantics_profile": "excel-subset-v1",
        }
        for field_name, expected in expected_versions.items():
            if getattr(self, field_name) != expected:
                raise ValueError(
                    f"Unregistered calculation version for {field_name}: "
                    f"{getattr(self, field_name)}"
                )
        integer_limits = (
            self.max_formula_length,
            self.max_tokens,
            self.max_nodes,
            self.max_depth,
            self.max_arguments,
            self.max_range_cells,
            self.max_formula_count,
            self.max_total_edges,
            self.max_trace_inputs,
        )
        if any(value <= 0 for value in integer_limits):
            raise ValueError("Calculation resource limits must be positive")
        if self.absolute_tolerance < 0 or self.relative_tolerance < 0:
            raise ValueError("Comparison tolerances must be non-negative")

    @property
    def configuration_hash(self) -> str:
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, order=True)
class WorkbookCellRef:
    workbook_version_id: str
    sheet_name: str
    sheet_position: int
    cell_address: str

    def __post_init__(self) -> None:
        uuid.UUID(self.workbook_version_id)
        if not self.sheet_name:
            raise ValueError("Sheet name must not be empty")
        if self.sheet_position < 0:
            raise ValueError("Sheet position must be non-negative")
        object.__setattr__(self, "cell_address", normalize_a1(self.cell_address))

    @property
    def key(self) -> tuple[int, str]:
        return self.sheet_position, self.cell_address

    @property
    def display(self) -> str:
        return f"{self.sheet_name}!{self.cell_address}"


CellValueType = Literal[
    "number",
    "boolean",
    "text",
    "blank",
    "date",
    "error",
]


@dataclass(frozen=True)
class WorkbookCellFact:
    ref: WorkbookCellRef
    value: Any
    value_type: CellValueType
    data_type: str | None
    number_format: str | None
    sheet_state: str
    formula_kind: str | None = None


@dataclass(frozen=True)
class WorkbookFormulaCell:
    id: str
    ref: WorkbookCellRef
    exact_formula: str
    formula_sha256: str
    formula_kind: Literal["scalar", "array", "data_table", "unknown_special"]
    cached_value: Any
    cached_value_type: CellValueType
    cache_status: Literal["available", "missing", "unavailable"]
    cache_freshness: Literal["missing", "unknown", "recalculation_required"]
    number_format: str | None
    data_type: str | None
    sheet_state: str
    special_range: str | None = None
    special_metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class WorkbookCatalog:
    workbook_version_id: str
    formulas: tuple[WorkbookFormulaCell, ...]
    sheet_names: tuple[str, ...]
    sheet_states: tuple[str, ...]
    workbook_date_system: Literal["1900", "1904"]
    recalculation_required: bool
    _cells: Mapping[tuple[int, str], WorkbookCellFact] = field(
        repr=False,
        compare=False,
    )

    def sheet_position(self, sheet_name: str) -> int | None:
        try:
            return self.sheet_names.index(sheet_name)
        except ValueError:
            return None

    def cell(self, reference: WorkbookCellRef) -> WorkbookCellFact:
        if reference.workbook_version_id != self.workbook_version_id:
            raise ValueError("Cell reference belongs to another workbook version")
        position = self.sheet_position(reference.sheet_name)
        if position is None or position != reference.sheet_position:
            raise ValueError("Cell reference does not match the workbook catalog")
        existing = self._cells.get(reference.key)
        if existing is not None:
            return existing
        return WorkbookCellFact(
            ref=reference,
            value=None,
            value_type="blank",
            data_type="n",
            number_format="General",
            sheet_state=self.sheet_states[reference.sheet_position],
        )

    def formula_by_ref(self) -> dict[WorkbookCellRef, WorkbookFormulaCell]:
        return {formula.ref: formula for formula in self.formulas}


@dataclass(frozen=True)
class FormulaReference:
    id: str
    expression_id: str
    formula_cell_id: str
    workbook_version_id: str
    ordinal: int
    source_token: str
    source_span_start: int
    source_span_end: int
    reference_kind: Literal["cell", "range"]
    target_classification: Literal["internal", "external", "unresolved"]
    target_sheet_name: str | None
    target_sheet_position: int | None
    start_cell_address: str | None
    end_cell_address: str | None
    start_column_absolute: bool
    start_row_absolute: bool
    end_column_absolute: bool | None
    end_row_absolute: bool | None
    range_rows: int | None
    range_columns: int | None
    resolution_status: Literal[
        "resolved_internal",
        "external",
        "missing_sheet",
        "invalid_address",
        "unsupported",
    ]
    warning_code: str | None = None

    @property
    def source_span(self) -> tuple[int, int]:
        return self.source_span_start, self.source_span_end

    @property
    def normalized_target(self) -> str:
        sheet = self.target_sheet_name or ""
        start = self.start_cell_address or ""
        if self.reference_kind == "range":
            return f"{sheet}!{start}:{self.end_cell_address or ''}"
        return f"{sheet}!{start}"


@dataclass(frozen=True)
class FormulaCompilation:
    expression_id: str
    formula_cell_id: str
    ir_version: str
    compiler_version: str
    semantics_profile: str
    formula_sha256: str
    normalized_signature: str | None
    parse_status: Literal["not_attempted", "parsed", "syntax_error"]
    support_status: Literal[
        "supported",
        "unsupported",
        "external_reference",
        "special_formula",
    ]
    ir_json: dict[str, Any] | None
    references: tuple[FormulaReference, ...]
    unsupported_constructs: tuple[str, ...]
    warnings: tuple[str, ...]


class FormulaIdFactory:
    """Generate retry-stable UUIDv5 identifiers from immutable inputs."""

    def __init__(self, workbook_version_id: str):
        self.workbook_version_id = str(uuid.UUID(workbook_version_id))
        self._workbook_namespace = uuid.UUID(self.workbook_version_id)

    def formula_cell_id(self, reference: WorkbookCellRef) -> str:
        if reference.workbook_version_id != self.workbook_version_id:
            raise ValueError("Formula cell belongs to another workbook version")
        key = "|".join(
            (
                "formula-cell",
                str(reference.sheet_position),
                reference.sheet_name,
                reference.cell_address,
            )
        )
        return str(uuid.uuid5(self._workbook_namespace, key))

    @staticmethod
    def expression_id(
        formula_cell_id: str,
        ir_version: str,
        compiler_version: str,
        semantics_profile: str,
        formula_sha256: str,
    ) -> str:
        key = "|".join(
            (ir_version, compiler_version, semantics_profile, formula_sha256)
        )
        return str(uuid.uuid5(uuid.UUID(formula_cell_id), key))

    @staticmethod
    def reference_id(
        formula_cell_id: str,
        expression_id: str,
        ordinal: int,
        source_span: tuple[int, int],
        reference_kind: str,
        normalized_target: str,
    ) -> str:
        key = "|".join(
            (
                expression_id,
                str(ordinal),
                str(source_span[0]),
                str(source_span[1]),
                reference_kind,
                normalized_target,
            )
        )
        return str(uuid.uuid5(uuid.UUID(formula_cell_id), key))

    @staticmethod
    def extraction_id(
        model_version_id: str,
        workbook_version_id: str,
        configuration: CalculationRuleExtractionConfiguration,
    ) -> str:
        key = "|".join(
            (
                workbook_version_id,
                configuration.inventory_version,
                configuration.compiler_version,
                configuration.engine_version,
                configuration.function_registry_version,
                configuration.semantics_profile,
                configuration.configuration_hash,
            )
        )
        return str(uuid.uuid5(uuid.UUID(model_version_id), key))

    @staticmethod
    def mapping_id(
        extraction_id: str,
        formula_cell_id: str,
        reference_id: str | None,
        mapping_role: str,
        canonical_target_id: str | None = None,
    ) -> str:
        key = "|".join(
            (
                "canonical-mapping",
                formula_cell_id,
                reference_id or "output",
                mapping_role,
                canonical_target_id or "unmapped",
            )
        )
        return str(uuid.uuid5(uuid.UUID(extraction_id), key))

    @staticmethod
    def execution_result_id(extraction_id: str, formula_cell_id: str) -> str:
        return str(
            uuid.uuid5(
                uuid.UUID(extraction_id),
                f"execution-result|{formula_cell_id}",
            )
        )


def value_type(value: Any, data_type: str | None = None) -> CellValueType:
    if value is None:
        return "blank"
    if data_type == "e":
        return "error"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, (datetime, date)):
        return "date"
    return "text"
