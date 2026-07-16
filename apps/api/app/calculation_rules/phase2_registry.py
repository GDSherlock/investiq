"""Closed function registry for the first progressive Phase 2 increment."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from .function_registry import FUNCTION_REGISTRY, FunctionDefinition


PHASE2_FUNCTION_REGISTRY_VERSION = "calc-functions-v2"
_KINDS = (
    "number",
    "boolean",
    "text",
    "blank",
    "date_serial",
    "error",
)


def _phase2_definition(
    name: str,
    minimum_arguments: int,
    maximum_arguments: int,
) -> FunctionDefinition:
    return FunctionDefinition(
        name=name,
        minimum_arguments=minimum_arguments,
        maximum_arguments=maximum_arguments,
        accepted_value_kinds=_KINDS,
        accepts_ranges=True,
        lazy=False,
        volatile=False,
        implementation_version=f"{name.lower()}-v2",
        conformance_version="excel-compatible-v2",
    )


PHASE2_FUNCTION_REGISTRY: Mapping[str, FunctionDefinition] = MappingProxyType(
    {
        **FUNCTION_REGISTRY,
        "COUNT": _phase2_definition("COUNT", 0, 255),
        "COUNTA": _phase2_definition("COUNTA", 0, 255),
        "COUNTIF": _phase2_definition("COUNTIF", 2, 2),
    }
)
