"""Strict role resolution for persisted calculation output projections."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .schemas import CalculationRunOutputItem


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


def normalized_analysis_label(label: str) -> str:
    """Normalize presentation-only differences without fuzzy matching."""

    without_unit = _TRAILING_UNIT.sub("", label.strip())
    return _WHITESPACE.sub(" ", without_unit.casefold())


def resolve_analysis_output(
    outputs: Iterable[CalculationRunOutputItem],
    semantic_role: str,
    *,
    entity_kind: str | None = None,
) -> CalculationRunOutputItem | None:
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
