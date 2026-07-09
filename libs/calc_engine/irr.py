"""IRR calculation — Newton-Raphson solver for Internal Rate of Return."""

from typing import Any


def _npv_at_rate(rate: float, cash_flows: list[float]) -> float:
    """Compute NPV at a given discount rate."""
    return sum(cf / (1 + rate) ** t for t, cf in enumerate(cash_flows))


def _npv_derivative(rate: float, cash_flows: list[float]) -> float:
    """Derivative of NPV w.r.t. rate for Newton-Raphson."""
    return sum(-t * cf / (1 + rate) ** (t + 1) for t, cf in enumerate(cash_flows))


def compute_irr(
    cash_flows: list[float],
    guess: float = 0.10,
    max_iterations: int = 200,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    """
    Compute IRR (unlevered) by solving NPV(r, FCF_t) = 0 using Newton-Raphson.

    Args:
        cash_flows: List of free cash flows, index 0 = Year 0.
        guess: Initial rate guess.
        max_iterations: Max Newton-Raphson iterations.
        tolerance: Convergence tolerance.

    Returns:
        Structured result dict with formula, inputs, result, confidence.
    """
    if not cash_flows or len(cash_flows) < 2:
        return {
            "formula_used": "IRR: solve NPV(r, FCF_t) = 0 via Newton-Raphson",
            "inputs": {"cash_flows": cash_flows},
            "result": None,
            "confidence": 0.0,
            "error": "Insufficient cash flows (need at least 2 periods)",
        }

    rate = guess
    converged = False

    for _ in range(max_iterations):
        npv_val = _npv_at_rate(rate, cash_flows)
        deriv = _npv_derivative(rate, cash_flows)

        if abs(deriv) < 1e-14:
            break

        new_rate = rate - npv_val / deriv
        if abs(new_rate - rate) < tolerance:
            converged = True
            rate = new_rate
            break
        rate = new_rate

    # Confidence based on convergence and residual
    residual = abs(_npv_at_rate(rate, cash_flows))
    if converged and residual < 1e-6:
        confidence = 1.0
    elif converged:
        confidence = 0.9
    else:
        confidence = 0.3

    return {
        "formula_used": "IRR: solve NPV(r, FCF_t) = 0 via Newton-Raphson",
        "inputs": {
            "cash_flows_count": len(cash_flows),
            "initial_guess": guess,
        },
        "result": round(rate, 6) if converged else None,
        "converged": converged,
        "iterations_used": min(max_iterations, _),
        "residual": residual,
        "confidence": confidence,
    }
