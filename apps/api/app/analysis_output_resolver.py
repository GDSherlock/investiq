"""Strict role resolution for persisted calculation output projections."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol, TypeVar


_TRAILING_UNIT = re.compile(
    r"\s*\((?:\$?\s*(?:m|mm|million)|(?:usd|sgd|eur|gbp)\s*(?:m|mm|million)|%|x)\)\s*$",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"\s+")

_LABEL_ALIASES: dict[str, frozenset[str]] = {
    "project_npv": frozenset({"project npv"}),
    "equity_npv": frozenset({"equity npv"}),
    "revenue": frozenset({"revenue", "total revenue"}),
    "ebitda": frozenset({"ebitda"}),
    "cfads": frozenset({"cfads"}),
    "project_free_cash_flow": frozenset(
        {"project free cash flow", "project fcf"}
    ),
    "equity_cash_flow": frozenset({"equity cash flow", "equity fcf"}),
    "operating_cash_flow": frozenset(
        {"operating cash flow", "cash flow from operations"}
    ),
    "debt_service": frozenset({"debt service", "total debt service"}),
    "dscr": frozenset({"dscr"}),
    "dscr_covenant": frozenset({"dscr covenant"}),
    "closing_debt": frozenset({"closing debt", "closing debt balance"}),
    "capex": frozenset({"capex", "capital expenditure"}),
    "interest_expense": frozenset({"interest expense"}),
    "principal_repayment": frozenset(
        {"principal repayment", "debt principal repayment"}
    ),
    "total_debt": frozenset({"total debt"}),
    "total_equity": frozenset({"total equity"}),
    "debt_ratio": frozenset({"debt ratio", "debt percentage"}),
    "equity_ratio": frozenset({"equity ratio", "equity percentage"}),
}

_PARAMETER_LABEL_ALIASES: dict[str, frozenset[str]] = {
    "debt_ratio": frozenset({"debt share", "debt ratio", "debt percentage"}),
    "discount_rate": frozenset({"discount rate", "wacc"}),
    "project_irr_hurdle": frozenset(
        {"project irr hurdle", "project irr hurdle rate"}
    ),
    "equity_irr_hurdle": frozenset(
        {"equity irr hurdle", "equity irr hurdle rate"}
    ),
    "dscr_covenant": frozenset(
        {"dscr covenant", "minimum dscr covenant"}
    ),
}


class _OutputLike(Protocol):
    entity_kind: str
    business_role: str
    label: str


class _ParameterLike(Protocol):
    business_role: str | None
    label: str


_OutputT = TypeVar("_OutputT", bound=_OutputLike)
_ParameterT = TypeVar("_ParameterT", bound=_ParameterLike)


def normalized_analysis_label(label: str) -> str:
    """Normalize presentation-only differences without fuzzy matching."""

    without_unit = _TRAILING_UNIT.sub("", label.strip())
    return _WHITESPACE.sub(" ", without_unit.casefold())


def resolve_analysis_output(
    outputs: Iterable[_OutputT],
    semantic_role: str,
    *,
    entity_kind: str | None = None,
) -> _OutputT | None:
    """Resolve one unambiguous output by role, then strict legacy label."""

    eligible = [
        output
        for output in outputs
        if entity_kind is None or output.entity_kind == entity_kind
    ]
    underlying_role = (
        "npv"
        if semantic_role in {"project_npv", "equity_npv"}
        else semantic_role
    )
    direct = [
        output
        for output in eligible
        if output.business_role == underlying_role
    ]
    aliases = _LABEL_ALIASES.get(semantic_role, frozenset())

    if len(direct) == 1 and semantic_role not in {
        "project_npv",
        "equity_npv",
    }:
        return direct[0]
    if aliases:
        labelled_direct = [
            output
            for output in direct
            if normalized_analysis_label(output.label) in aliases
        ]
        if len(labelled_direct) == 1:
            return labelled_direct[0]
    if direct:
        return None

    labelled_legacy = [
        output
        for output in eligible
        if output.business_role == "unclassified"
        and normalized_analysis_label(output.label) in aliases
    ]
    return labelled_legacy[0] if len(labelled_legacy) == 1 else None


def resolve_analysis_parameter(
    parameters: Iterable[_ParameterT],
    semantic_role: str,
) -> _ParameterT | None:
    """Resolve one benchmark parameter without requiring a binding row."""

    candidates = list(parameters)
    direct = [
        parameter
        for parameter in candidates
        if parameter.business_role == semantic_role
    ]
    if len(direct) == 1:
        return direct[0]
    if direct:
        return None
    aliases = _PARAMETER_LABEL_ALIASES.get(semantic_role, frozenset())
    legacy = [
        parameter
        for parameter in candidates
        if parameter.business_role is None
        and normalized_analysis_label(parameter.label) in aliases
    ]
    return legacy[0] if len(legacy) == 1 else None
