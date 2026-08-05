"""Closed function registry for the first progressive Phase 2 increment."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from .function_registry import FUNCTION_REGISTRY, FunctionDefinition
from .phase2_types import (
    PHASE2_FUNCTION_REGISTRY_VERSION,
    PHASE2_SEMANTICS_PROFILE,
)


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
    *,
    lazy: bool = False,
) -> FunctionDefinition:
    return FunctionDefinition(
        name=name,
        minimum_arguments=minimum_arguments,
        maximum_arguments=maximum_arguments,
        accepted_value_kinds=_KINDS,
        accepts_ranges=True,
        lazy=lazy,
        volatile=False,
        implementation_version=f"{name.lower()}-v2",
        conformance_version=PHASE2_SEMANTICS_PROFILE,
    )


PHASE2_FUNCTION_REGISTRY: Mapping[str, FunctionDefinition] = MappingProxyType(
    {
        **FUNCTION_REGISTRY,
        "COUNT": _phase2_definition("COUNT", 0, 255),
        "COUNTA": _phase2_definition("COUNTA", 0, 255),
        "COUNTIF": _phase2_definition("COUNTIF", 2, 2),
        "IFERROR": _phase2_definition("IFERROR", 2, 2, lazy=True),
        "AND": _phase2_definition("AND", 1, 255),
        "OR": _phase2_definition("OR", 1, 255),
        "MINIFS": _phase2_definition("MINIFS", 3, 253),
        "IRR": _phase2_definition("IRR", 1, 2),
        "NPV": _phase2_definition("NPV", 2, 255),
        "MOD": _phase2_definition("MOD", 2, 2),
        "YEAR": _phase2_definition("YEAR", 1, 1),
        "MATCH": _phase2_definition("MATCH", 2, 3),
    }
)
