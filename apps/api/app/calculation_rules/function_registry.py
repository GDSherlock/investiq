"""Closed, versioned function metadata for the Phase 1 Excel subset."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


FUNCTION_REGISTRY_VERSION = "function-registry-v1"


@dataclass(frozen=True)
class FunctionDefinition:
    name: str
    minimum_arguments: int
    maximum_arguments: int
    accepted_value_kinds: tuple[str, ...]
    accepts_ranges: bool
    lazy: bool
    volatile: bool
    implementation_version: str
    conformance_version: str


def _definition(
    name: str,
    minimum_arguments: int,
    maximum_arguments: int,
    *,
    accepts_ranges: bool,
    lazy: bool = False,
) -> FunctionDefinition:
    return FunctionDefinition(
        name=name,
        minimum_arguments=minimum_arguments,
        maximum_arguments=maximum_arguments,
        accepted_value_kinds=(
            "number",
            "boolean",
            "text",
            "blank",
            "date_serial",
            "error",
        ),
        accepts_ranges=accepts_ranges,
        lazy=lazy,
        volatile=False,
        implementation_version=f"{name.lower()}-v1",
        conformance_version="excel-subset-v1",
    )


FUNCTION_REGISTRY: Mapping[str, FunctionDefinition] = MappingProxyType(
    {
        "SUM": _definition("SUM", 0, 255, accepts_ranges=True),
        "AVERAGE": _definition("AVERAGE", 0, 255, accepts_ranges=True),
        "MIN": _definition("MIN", 0, 255, accepts_ranges=True),
        "MAX": _definition("MAX", 0, 255, accepts_ranges=True),
        "ABS": _definition("ABS", 1, 1, accepts_ranges=False),
        "ROUND": _definition("ROUND", 2, 2, accepts_ranges=False),
        "IF": _definition("IF", 2, 3, accepts_ranges=False, lazy=True),
    }
)
