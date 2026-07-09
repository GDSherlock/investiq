"""DSCR calculation — Debt Service Coverage Ratio with covenant checks."""

from typing import Any


def compute_dscr(
    ebitda: list[float],
    interest: list[float],
    principal: list[float],
) -> dict[str, Any]:
    """
    Compute annual DSCR = EBITDA / (Interest + Scheduled Principal).

    Args:
        ebitda: Annual EBITDA values.
        interest: Annual interest expense (positive values).
        principal: Annual scheduled principal repayment (positive values).

    Returns:
        Structured result dict with per-year DSCR and summary stats.
    """
    n = min(len(ebitda), len(interest), len(principal))
    dscr_values = []

    for i in range(n):
        total_debt_service = abs(interest[i]) + abs(principal[i])
        if total_debt_service == 0:
            dscr_values.append({"year_index": i, "dscr": None, "debt_service": 0})
        else:
            dscr = ebitda[i] / total_debt_service
            dscr_values.append({
                "year_index": i,
                "dscr": round(dscr, 4),
                "ebitda": round(ebitda[i], 4),
                "debt_service": round(total_debt_service, 4),
            })

    # Filter valid DSCR
    valid = [d["dscr"] for d in dscr_values if d["dscr"] is not None]
    avg_dscr = sum(valid) / len(valid) if valid else None
    min_dscr = min(valid) if valid else None
    min_year = None
    if min_dscr is not None:
        for d in dscr_values:
            if d["dscr"] == min_dscr:
                min_year = d["year_index"]
                break

    return {
        "formula_used": "DSCR = EBITDA / (Interest + Scheduled Principal)",
        "inputs": {"periods": n},
        "result": {
            "average_dscr": round(avg_dscr, 4) if avg_dscr else None,
            "minimum_dscr": round(min_dscr, 4) if min_dscr else None,
            "minimum_year_index": min_year,
        },
        "annual_dscr": dscr_values,
        "confidence": 1.0,
    }


def check_covenant(
    dscr_value: float,
    breach_threshold: float = 1.25,
    amber_threshold: float = 1.35,
) -> dict[str, Any]:
    """
    Check DSCR against covenant thresholds.

    ≥ amber_threshold → GREEN
    ≥ breach_threshold and < amber_threshold → AMBER
    < breach_threshold → BREACH (RED)

    Args:
        dscr_value: The DSCR to evaluate.
        breach_threshold: Below this = covenant breach.
        amber_threshold: Below this (but above breach) = warning.

    Returns:
        Covenant status result.
    """
    if dscr_value >= amber_threshold:
        status = "GREEN"
    elif dscr_value >= breach_threshold:
        status = "AMBER"
    else:
        status = "BREACH"

    return {
        "formula_used": "Covenant check: BREACH < 1.25x; AMBER < 1.35x; GREEN >= 1.35x",
        "inputs": {
            "dscr_value": dscr_value,
            "breach_threshold": breach_threshold,
            "amber_threshold": amber_threshold,
        },
        "result": status,
        "confidence": 1.0,
    }
