"""Versioned contracts for the additive Phase 2 calculation engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import hashlib
import json
import math
from typing import Any, Mapping
import uuid

from .types import normalize_a1


PHASE2_INVENTORY_VERSION = "formula-inventory-v1"
PHASE2_IR_VERSION = "calc-ir-v2"
PHASE2_COMPILER_VERSION = "formula-compiler-v3"
PHASE2_ENGINE_VERSION = "calc-engine-v4"
PHASE2_FUNCTION_REGISTRY_VERSION = "calc-functions-v4"
PHASE2_SEMANTICS_PROFILE = "excel-compatible-kpi-v1"
PHASE2_GROUPING_PROFILE = "relative-ast-v1"


@dataclass(frozen=True)
class Phase2CalculationConfiguration:
    inventory_version: str = PHASE2_INVENTORY_VERSION
    ir_version: str = PHASE2_IR_VERSION
    compiler_version: str = PHASE2_COMPILER_VERSION
    engine_version: str = PHASE2_ENGINE_VERSION
    function_registry_version: str = PHASE2_FUNCTION_REGISTRY_VERSION
    semantics_profile: str = PHASE2_SEMANTICS_PROFILE
    grouping_profile: str = PHASE2_GROUPING_PROFILE
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
        expected = {
            "inventory_version": PHASE2_INVENTORY_VERSION,
            "ir_version": PHASE2_IR_VERSION,
            "compiler_version": PHASE2_COMPILER_VERSION,
            "engine_version": PHASE2_ENGINE_VERSION,
            "function_registry_version": PHASE2_FUNCTION_REGISTRY_VERSION,
            "semantics_profile": PHASE2_SEMANTICS_PROFILE,
            "grouping_profile": PHASE2_GROUPING_PROFILE,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(
                    f"Unregistered Phase 2 calculation version for {field_name}: "
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
            raise ValueError("Phase 2 calculation resource limits must be positive")
        if self.absolute_tolerance < 0 or self.relative_tolerance < 0:
            raise ValueError("Phase 2 comparison tolerances must be non-negative")

    @property
    def configuration_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CalculationOverride:
    target_kind: str
    target_id: str | None
    sheet_name: str | None
    cell_address: str | None
    value_type: str
    value: Any

    def __post_init__(self) -> None:
        if self.target_kind == "parameter":
            if self.target_id is None or self.sheet_name is not None or self.cell_address is not None:
                raise ValueError("Parameter override target is invalid")
            uuid.UUID(self.target_id)
        elif self.target_kind == "cell":
            if self.target_id is not None or not self.sheet_name or self.cell_address is None:
                raise ValueError("Cell override target is invalid")
            object.__setattr__(self, "cell_address", normalize_a1(self.cell_address))
        else:
            raise ValueError("Override target kind is not registered")
        if self.value_type not in {"number", "boolean", "text", "blank", "date"}:
            raise ValueError("Override value type is not registered")
        if self.value_type == "text" and str(self.value).startswith("="):
            raise ValueError("Formula text is not an allowed override")
        if self.value_type == "number" and not math.isfinite(float(self.value)):
            raise ValueError("Override number must be finite")

    @classmethod
    def parameter(cls, parameter_id: str, value: Any) -> "CalculationOverride":
        value_type, normalized = _normalize_override_value(value)
        return cls("parameter", str(uuid.UUID(parameter_id)), None, None, value_type, normalized)

    @classmethod
    def cell(
        cls,
        sheet_name: str,
        cell_address: str,
        value: Any,
    ) -> "CalculationOverride":
        value_type, normalized = _normalize_override_value(value)
        return cls("cell", None, sheet_name, cell_address, value_type, normalized)

    def to_payload(self) -> dict[str, Any]:
        value = self.value.isoformat() if isinstance(self.value, (date, datetime)) else self.value
        return {
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "sheet_name": self.sheet_name,
            "cell_address": self.cell_address,
            "value_type": self.value_type,
            "value": value,
        }


@dataclass(frozen=True)
class CalculationRunPolicy:
    iteration_enabled: bool = False
    volatile_functions_enabled: bool = False
    reuse_compatible_values: bool = True
    deterministic_parallelism: bool = False

    def __post_init__(self) -> None:
        if self.iteration_enabled:
            raise ValueError("Iterative calculation policy is not approved")
        if self.volatile_functions_enabled:
            raise ValueError("Volatile calculation policy is not approved")

    def to_payload(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(frozen=True)
class WorkbookCompilationResult:
    workbook_version_id: str
    graph_version_id: str
    ir_version: str
    compiler_version: str
    function_registry_version: str
    semantics_profile: str
    formula_cells_total: int
    formula_cells_supported: int
    formula_cells_unsupported: int
    graph_nodes: int
    graph_edges: int


@dataclass(frozen=True)
class CalculationCellResult:
    formula_cell_id: str
    expression_id: str
    sheet_name: str
    sheet_position: int
    cell_address: str
    status: str
    value: Any
    engine_error_code: str | None
    reused_from_run_id: str | None
    validation_status: str
    warnings: tuple[str, ...]

    @property
    def display(self) -> str:
        return f"{self.sheet_name}!{self.cell_address}"


@dataclass(frozen=True)
class CalculationRunResult:
    calculation_run_id: str
    model_version_id: str
    graph_version_id: str
    base_run_id: str | None
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
        return {cell.display: cell for cell in self.cells}

    @property
    def reused_formula_cells(self) -> int:
        return sum(cell.status == "reused" for cell in self.cells)


def canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_override_value(value: Any) -> tuple[str, Any]:
    if value is None:
        return "blank", None
    if isinstance(value, bool):
        return "boolean", value
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Override number must be finite")
        return "number", number
    if isinstance(value, (date, datetime)):
        return "date", value
    if isinstance(value, str):
        if value.startswith("="):
            raise ValueError("Formula text is not an allowed override")
        return "text", value
    raise ValueError("Override value type is not registered")
