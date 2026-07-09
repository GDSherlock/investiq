"""NPV calculation — Net Present Value."""

from typing import Any


def compute_npv(
    cash_flows: list[float],
    wacc: float,
    start_year: int | None = None,
) -> dict[str, Any]:
    """
    Compute NPV = Σ(FCF_t / (1 + WACC)^t).

    Args:
        cash_flows: Free cash flows starting from period 0.
        wacc: Weighted Average Cost of Capital (decimal, e.g. 0.085).
        start_year: Optional label for the first year.

    Returns:
        Structured result dict.
    """
    if wacc <= -1:
        return {
            "formula_used": "NPV = Σ(FCF_t / (1 + WACC)^t)",
            "inputs": {"wacc": wacc, "cash_flows_count": len(cash_flows)},
            "result": None,
            "confidence": 0.0,
            "error": "WACC must be greater than -1",
        }

    npv = sum(cf / (1 + wacc) ** t for t, cf in enumerate(cash_flows))

    # Per-period breakdown
    pv_breakdown = []
    for t, cf in enumerate(cash_flows):
        discount_factor = 1 / (1 + wacc) ** t
        pv = cf * discount_factor
        year_label = (start_year + t) if start_year else t
        pv_breakdown.append({
            "period": year_label,
            "cash_flow": round(cf, 4),
            "discount_factor": round(discount_factor, 6),
            "present_value": round(pv, 4),
        })

    return {
        "formula_used": "NPV = Σ(FCF_t / (1 + WACC)^t)",
        "inputs": {
            "wacc": wacc,
            "cash_flows_count": len(cash_flows),
            "start_year": start_year,
        },
        "result": round(npv, 4),
        "pv_breakdown": pv_breakdown,
        "confidence": 1.0,
    }
