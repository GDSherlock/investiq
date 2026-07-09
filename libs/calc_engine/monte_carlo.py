"""Monte Carlo simulation engine — Box-Muller, Cholesky, percentile extraction."""

import math
import random
from typing import Any


def box_muller_normal(n: int, seed: int | None = None) -> list[float]:
    """
    Generate n standard normal samples using Box-Muller transform.

    Args:
        n: Number of samples.
        seed: Optional random seed for reproducibility.

    Returns:
        List of standard normal samples.
    """
    if seed is not None:
        random.seed(seed)

    samples = []
    for _ in range((n + 1) // 2):
        u1 = random.random()
        u2 = random.random()
        # Avoid log(0)
        while u1 == 0:
            u1 = random.random()
        z0 = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
        z1 = math.sqrt(-2 * math.log(u1)) * math.sin(2 * math.pi * u2)
        samples.append(z0)
        if len(samples) < n:
            samples.append(z1)

    return samples[:n]


def cholesky_decomposition(matrix: list[list[float]]) -> list[list[float]]:
    """
    Compute Cholesky decomposition of a positive-definite correlation matrix.

    Args:
        matrix: Correlation matrix (symmetric, positive-definite).

    Returns:
        Lower triangular matrix L such that matrix = L @ L^T.
    """
    n = len(matrix)
    L = [[0.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(i + 1):
            s = sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                val = matrix[i][i] - s
                if val < 0:
                    raise ValueError("Matrix is not positive-definite")
                L[i][j] = math.sqrt(val)
            else:
                if L[j][j] == 0:
                    raise ValueError("Matrix is singular")
                L[i][j] = (matrix[i][j] - s) / L[j][j]

    return L


def _lognormal_sample(mean: float, std: float, z: float) -> float:
    """Convert a standard normal sample to log-normal."""
    sigma_sq = math.log(1 + (std / mean) ** 2) if mean != 0 else std ** 2
    mu = math.log(abs(mean)) - sigma_sq / 2 if mean != 0 else 0
    sigma = math.sqrt(sigma_sq)
    return math.exp(mu + sigma * z)


def monte_carlo_simulation(
    base_assumptions: dict[str, float],
    volatilities: dict[str, float],
    correlation_matrix: list[list[float]] | None = None,
    n_simulations: int = 10000,
    distribution: str = "normal",
    seed: int | None = 42,
    cash_flow_func: Any = None,
) -> dict[str, Any]:
    """
    Run Monte Carlo simulation over assumption variables.

    Args:
        base_assumptions: Dict of variable_name -> base_value.
        volatilities: Dict of variable_name -> std_dev (absolute or relative).
        correlation_matrix: Optional correlation matrix for variables.
        n_simulations: Number of simulation runs.
        distribution: 'normal' or 'lognormal'.
        seed: Random seed.
        cash_flow_func: Optional callable(assumptions_dict) -> scalar metric.

    Returns:
        Structured result with P10/P50/P90, histogram data, VaR.
    """
    var_names = list(base_assumptions.keys())
    n_vars = len(var_names)

    # Generate correlated normal samples
    if seed is not None:
        random.seed(seed)

    # Cholesky for correlation
    if correlation_matrix and n_vars > 1:
        L = cholesky_decomposition(correlation_matrix)
    else:
        L = [[1.0 if i == j else 0.0 for j in range(n_vars)] for i in range(n_vars)]

    # Generate raw normal samples
    all_normals = []
    for _ in range(n_simulations):
        z = [box_muller_normal(1)[0] for _ in range(n_vars)]
        # Apply Cholesky correlation
        correlated = [
            sum(L[i][j] * z[j] for j in range(n_vars)) for i in range(n_vars)
        ]
        all_normals.append(correlated)

    # Apply to assumptions and compute metric
    results = []
    simulated_assumptions = []

    for sim_normals in all_normals:
        scenario = {}
        for idx, var in enumerate(var_names):
            base = base_assumptions[var]
            vol = volatilities.get(var, 0)
            z_val = sim_normals[idx]

            if distribution == "lognormal" and base > 0:
                scenario[var] = _lognormal_sample(base, vol, z_val)
            else:
                scenario[var] = base + vol * z_val

        simulated_assumptions.append(scenario)

        if cash_flow_func:
            metric = cash_flow_func(scenario)
            results.append(metric)

    # If no cash_flow_func, compute stats on first variable
    if not results and simulated_assumptions:
        first_var = var_names[0]
        results = [s[first_var] for s in simulated_assumptions]

    results.sort()
    n = len(results)

    p10 = results[int(n * 0.10)] if n > 0 else None
    p50 = results[int(n * 0.50)] if n > 0 else None
    p90 = results[int(n * 0.90)] if n > 0 else None
    mean_val = sum(results) / n if n > 0 else None
    std_val = (sum((x - mean_val) ** 2 for x in results) / n) ** 0.5 if n > 0 else None

    # VaR at 95% confidence
    var_95 = results[int(n * 0.05)] if n > 0 else None

    # Histogram bins
    n_bins = 50
    if n > 0:
        min_r, max_r = results[0], results[-1]
        bin_width = (max_r - min_r) / n_bins if max_r != min_r else 1
        histogram = []
        for b in range(n_bins):
            low = min_r + b * bin_width
            high = low + bin_width
            if b == n_bins - 1:
                count = sum(1 for x in results if low <= x <= high)
            else:
                count = sum(1 for x in results if low <= x < high)
            histogram.append({
                "bin_low": round(low, 4),
                "bin_high": round(high, 4),
                "count": count,
                "frequency": round(count / n, 4),
            })
    else:
        histogram = []

    return {
        "formula_used": f"Monte Carlo ({distribution}), Box-Muller sampling, Cholesky correlation",
        "inputs": {
            "n_simulations": n_simulations,
            "distribution": distribution,
            "variables": var_names,
            "base_assumptions": base_assumptions,
        },
        "result": {
            "p10": round(p10, 6) if p10 is not None else None,
            "p50": round(p50, 6) if p50 is not None else None,
            "p90": round(p90, 6) if p90 is not None else None,
            "mean": round(mean_val, 6) if mean_val is not None else None,
            "std_dev": round(std_val, 6) if std_val is not None else None,
            "var_95": round(var_95, 6) if var_95 is not None else None,
        },
        "histogram": histogram,
        "confidence": 0.95 if n_simulations >= 10000 else 0.8,
    }
