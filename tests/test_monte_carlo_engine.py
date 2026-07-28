from __future__ import annotations

import math

import pytest

from apps.api.app.monte_carlo_engine import (
    MonteCarloCancelled,
    simulate_surrogate,
    validate_correlation_matrix,
    validate_distribution,
)


@pytest.mark.parametrize(
    ("family", "parameters"),
    [
        ("normal", {"mean": 10.0, "stddev": 1.0}),
        ("triangular", {"low": 8.0, "mode": 10.0, "high": 14.0}),
        ("uniform", {"low": 8.0, "high": 12.0}),
        ("lognormal", {"log_mean": 2.0, "log_stddev": 0.2}),
        (
            "discrete",
            {"values": [8.0, 10.0, 12.0], "probabilities": [0.2, 0.5, 0.3]},
        ),
    ],
)
def test_five_supported_distribution_families_are_finite(
    family: str,
    parameters: dict[str, object],
) -> None:
    normalized = validate_distribution(family, parameters)

    assert normalized["family"] == family
    assert all(
        math.isfinite(float(value))
        for value in normalized["support"]
    )


@pytest.mark.parametrize(
    "matrix",
    [
        [[1.0, 0.2], [0.1, 1.0]],
        [[1.0, 1.2], [1.2, 1.0]],
        [[1.0, -1.0], [-1.0, 1.0]],
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    ],
)
def test_invalid_correlation_matrices_are_rejected(
    matrix: list[list[float]],
) -> None:
    with pytest.raises(ValueError):
        validate_correlation_matrix(matrix, 2)


def _simulation(seed: int, trial_count: int = 2_000) -> dict[str, object]:
    return simulate_surrogate(
        trial_count=trial_count,
        random_seed=seed,
        inputs=[
            {
                "parameter_id": "parameter-a",
                "label": "Driver A",
                "distribution_type": "normal",
                "distribution_parameters": {
                    "mean": 10.0,
                    "stddev": 1.0,
                },
            },
            {
                "parameter_id": "parameter-b",
                "label": "Driver B",
                "distribution_type": "uniform",
                "distribution_parameters": {
                    "low": 0.0,
                    "high": 1.0,
                },
            },
        ],
        correlation_matrix=[[1.0, 0.25], [0.25, 1.0]],
        surrogates=[
            {
                "role": "project_irr",
                "label": "Project IRR",
                "intercept": 0.12,
                "centers": {
                    "parameter-a": 10.0,
                    "parameter-b": 0.5,
                },
                "coefficients": {
                    "parameter-a": 0.01,
                    "parameter-b": -0.03,
                },
                "availability_status": "available",
                "holdout_relative_error": 0.01,
            },
            {
                "role": "project_npv",
                "label": "Project NPV",
                "intercept": 100.0,
                "centers": {
                    "parameter-a": 10.0,
                    "parameter-b": 0.5,
                },
                "coefficients": {
                    "parameter-a": 5.0,
                    "parameter-b": -20.0,
                },
                "availability_status": "available",
                "holdout_relative_error": 0.02,
            },
        ],
        benchmarks={"project_irr": 0.1},
    )


def test_fixed_seed_reproduces_percentiles_distributions_and_rankings() -> None:
    first = _simulation(42)
    second = _simulation(42)
    different = _simulation(43)

    assert first == second
    assert first != different


def test_fifty_thousand_trials_return_bounded_artifacts_not_trial_rows() -> None:
    result = _simulation(7, trial_count=50_000)

    assert result["trial_count"] == 50_000
    assert "trial_results" not in result
    metrics = result["metrics"]
    assert isinstance(metrics, list)
    assert all(len(metric["distribution"]["bins"]) <= 40 for metric in metrics)


def test_simulation_honors_cancellation_between_batches() -> None:
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks > 2

    with pytest.raises(MonteCarloCancelled):
        simulate_surrogate(
            trial_count=50_000,
            random_seed=1,
            inputs=[
                {
                    "parameter_id": "parameter-a",
                    "label": "Driver A",
                    "distribution_type": "normal",
                    "distribution_parameters": {
                        "mean": 1.0,
                        "stddev": 0.1,
                    },
                }
            ],
            correlation_matrix=[[1.0]],
            surrogates=[
                {
                    "role": "project_irr",
                    "label": "Project IRR",
                    "intercept": 0.1,
                    "centers": {"parameter-a": 1.0},
                    "coefficients": {"parameter-a": 0.01},
                    "availability_status": "available",
                    "holdout_relative_error": 0.01,
                }
            ],
            benchmarks={},
            is_cancelled=cancelled,
        )
