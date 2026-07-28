"""Deterministic, bounded Monte Carlo sampling over validated surrogates."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import math
import random
from statistics import NormalDist
from typing import Any


MONTE_CARLO_METHOD_VERSION = "canonical-linear-surrogate-v1"
_NORMAL = NormalDist()
_MATRIX_TOLERANCE = 1e-10
_HISTOGRAM_BIN_LIMIT = 30
_CANCELLATION_BATCH = 1_000


class MonteCarloCancelled(RuntimeError):
    pass


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def validate_distribution(
    family: str,
    parameters: Mapping[str, object],
) -> dict[str, Any]:
    if family == "normal":
        mean = _finite_number(parameters.get("mean"), "mean")
        stddev = _finite_number(parameters.get("stddev"), "stddev")
        if stddev <= 0:
            raise ValueError("normal stddev must be positive")
        normalized = {"mean": mean, "stddev": stddev}
        support = [mean - 4 * stddev, mean + 4 * stddev]
    elif family == "triangular":
        low = _finite_number(parameters.get("low"), "low")
        mode = _finite_number(parameters.get("mode"), "mode")
        high = _finite_number(parameters.get("high"), "high")
        if not low < high or not low <= mode <= high:
            raise ValueError("triangular requires low <= mode <= high")
        normalized = {"low": low, "mode": mode, "high": high}
        support = [low, high]
    elif family == "uniform":
        low = _finite_number(parameters.get("low"), "low")
        high = _finite_number(parameters.get("high"), "high")
        if not low < high:
            raise ValueError("uniform requires low < high")
        normalized = {"low": low, "high": high}
        support = [low, high]
    elif family == "lognormal":
        log_mean = _finite_number(
            parameters.get("log_mean"),
            "log_mean",
        )
        log_stddev = _finite_number(
            parameters.get("log_stddev"),
            "log_stddev",
        )
        if log_stddev <= 0:
            raise ValueError("lognormal log_stddev must be positive")
        normalized = {
            "log_mean": log_mean,
            "log_stddev": log_stddev,
        }
        support = [
            math.exp(log_mean - 4 * log_stddev),
            math.exp(log_mean + 4 * log_stddev),
        ]
    elif family == "discrete":
        raw_values = parameters.get("values")
        raw_probabilities = parameters.get("probabilities")
        if (
            not isinstance(raw_values, list)
            or not isinstance(raw_probabilities, list)
            or len(raw_values) < 2
            or len(raw_values) != len(raw_probabilities)
        ):
            raise ValueError(
                "discrete values and probabilities must have equal length"
            )
        values = [
            _finite_number(value, "discrete value")
            for value in raw_values
        ]
        probabilities = [
            _finite_number(value, "discrete probability")
            for value in raw_probabilities
        ]
        if any(value < 0 for value in probabilities) or not math.isclose(
            sum(probabilities),
            1.0,
            rel_tol=0,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "discrete probabilities must be non-negative and sum to one"
            )
        normalized = {
            "values": values,
            "probabilities": probabilities,
        }
        support = [min(values), max(values)]
    else:
        raise ValueError(f"Unsupported distribution family: {family}")
    return {
        "family": family,
        "parameters": normalized,
        "support": support,
    }


def validate_correlation_matrix(
    matrix: Sequence[Sequence[object]],
    size: int,
) -> list[list[float]]:
    if size < 1 or len(matrix) != size:
        raise ValueError("correlation matrix dimensions do not match inputs")
    normalized: list[list[float]] = []
    for row in matrix:
        if len(row) != size:
            raise ValueError(
                "correlation matrix dimensions do not match inputs"
            )
        normalized.append(
            [_finite_number(value, "correlation") for value in row]
        )
    for row_index in range(size):
        if not math.isclose(
            normalized[row_index][row_index],
            1.0,
            rel_tol=0,
            abs_tol=_MATRIX_TOLERANCE,
        ):
            raise ValueError("correlation matrix diagonal must equal one")
        for column_index in range(size):
            value = normalized[row_index][column_index]
            if value < -1 or value > 1:
                raise ValueError(
                    "correlation coefficients must be between -1 and one"
                )
            if not math.isclose(
                value,
                normalized[column_index][row_index],
                rel_tol=0,
                abs_tol=_MATRIX_TOLERANCE,
            ):
                raise ValueError("correlation matrix must be symmetric")
    _cholesky(normalized)
    return normalized


def _cholesky(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    size = len(matrix)
    result = [[0.0] * size for _ in range(size)]
    for row in range(size):
        for column in range(row + 1):
            remainder = matrix[row][column] - sum(
                result[row][index] * result[column][index]
                for index in range(column)
            )
            if row == column:
                if remainder <= _MATRIX_TOLERANCE:
                    raise ValueError(
                        "correlation matrix must be positive definite"
                    )
                result[row][column] = math.sqrt(remainder)
            else:
                result[row][column] = (
                    remainder / result[column][column]
                )
    return result


def _sample_from_distribution(
    normalized: Mapping[str, Any],
    normal_value: float,
) -> float:
    family = normalized["family"]
    parameters = normalized["parameters"]
    if family == "normal":
        return (
            parameters["mean"] + parameters["stddev"] * normal_value
        )
    if family == "lognormal":
        return math.exp(
            parameters["log_mean"]
            + parameters["log_stddev"] * normal_value
        )
    uniform_value = min(
        max(_NORMAL.cdf(normal_value), 1e-15),
        1 - 1e-15,
    )
    if family == "uniform":
        return parameters["low"] + uniform_value * (
            parameters["high"] - parameters["low"]
        )
    if family == "triangular":
        low = parameters["low"]
        mode = parameters["mode"]
        high = parameters["high"]
        split = (mode - low) / (high - low)
        if uniform_value <= split:
            return low + math.sqrt(
                uniform_value * (high - low) * (mode - low)
            )
        return high - math.sqrt(
            (1 - uniform_value) * (high - low) * (high - mode)
        )
    cumulative = 0.0
    for value, probability in zip(
        parameters["values"],
        parameters["probabilities"],
        strict=True,
    ):
        cumulative += probability
        if uniform_value <= cumulative:
            return value
    return parameters["values"][-1]


def _percentile(sorted_values: Sequence[float], percentile: float) -> float:
    if not sorted_values:
        raise ValueError("percentile requires observations")
    position = percentile * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return (
        sorted_values[lower] * (1 - weight)
        + sorted_values[upper] * weight
    )


def _histogram(values: Sequence[float]) -> dict[str, object]:
    minimum = min(values)
    maximum = max(values)
    if math.isclose(minimum, maximum):
        return {
            "bins": [
                {
                    "lower": minimum,
                    "upper": maximum,
                    "count": len(values),
                }
            ]
        }
    bin_count = min(
        _HISTOGRAM_BIN_LIMIT,
        max(10, int(math.sqrt(len(values)))),
    )
    width = (maximum - minimum) / bin_count
    counts = [0] * bin_count
    for value in values:
        index = min(int((value - minimum) / width), bin_count - 1)
        counts[index] += 1
    return {
        "bins": [
            {
                "lower": minimum + index * width,
                "upper": minimum + (index + 1) * width,
                "count": count,
            }
            for index, count in enumerate(counts)
        ]
    }


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    )
    left_scale = math.sqrt(
        sum((value - left_mean) ** 2 for value in left)
    )
    right_scale = math.sqrt(
        sum((value - right_mean) ** 2 for value in right)
    )
    if left_scale == 0 or right_scale == 0:
        return 0.0
    return numerator / (left_scale * right_scale)


def simulate_surrogate(
    *,
    trial_count: int,
    random_seed: int,
    inputs: Sequence[Mapping[str, Any]],
    correlation_matrix: Sequence[Sequence[object]],
    surrogates: Sequence[Mapping[str, Any]],
    benchmarks: Mapping[str, float],
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, object]:
    if trial_count < 1 or trial_count > 50_000:
        raise ValueError("trial_count must be between one and 50,000")
    if not inputs:
        raise ValueError("at least one stochastic input is required")
    normalized_inputs = [
        {
            **dict(item),
            "distribution": validate_distribution(
                str(item["distribution_type"]),
                item["distribution_parameters"],
            ),
        }
        for item in inputs
    ]
    normalized_matrix = validate_correlation_matrix(
        correlation_matrix,
        len(normalized_inputs),
    )
    cholesky = _cholesky(normalized_matrix)
    rng = random.Random(random_seed)
    input_samples = {
        str(item["parameter_id"]): [] for item in normalized_inputs
    }
    output_samples = {
        str(surrogate["role"]): []
        for surrogate in surrogates
        if surrogate.get("availability_status") == "available"
    }

    for trial_index in range(trial_count):
        if (
            trial_index % _CANCELLATION_BATCH == 0
            and is_cancelled is not None
            and is_cancelled()
        ):
            raise MonteCarloCancelled("Monte Carlo run was cancelled")
        independent = [
            rng.gauss(0.0, 1.0) for _ in normalized_inputs
        ]
        correlated = [
            sum(
                cholesky[row][column] * independent[column]
                for column in range(row + 1)
            )
            for row in range(len(normalized_inputs))
        ]
        sampled: dict[str, float] = {}
        for index, item in enumerate(normalized_inputs):
            parameter_id = str(item["parameter_id"])
            value = _sample_from_distribution(
                item["distribution"],
                correlated[index],
            )
            sampled[parameter_id] = value
            input_samples[parameter_id].append(value)
        for surrogate in surrogates:
            if surrogate.get("availability_status") != "available":
                continue
            role = str(surrogate["role"])
            value = float(surrogate["intercept"])
            centers = surrogate["centers"]
            coefficients = surrogate["coefficients"]
            for parameter_id, coefficient in coefficients.items():
                value += float(coefficient) * (
                    sampled[str(parameter_id)]
                    - float(centers[str(parameter_id)])
                )
            output_samples[role].append(value)

    metrics: list[dict[str, object]] = []
    labels_by_parameter = {
        str(item["parameter_id"]): str(item["label"])
        for item in normalized_inputs
    }
    for surrogate in surrogates:
        role = str(surrogate["role"])
        if surrogate.get("availability_status") != "available":
            metrics.append(
                {
                    "role": role,
                    "label": str(surrogate.get("label", role)),
                    "availability_status": "unavailable",
                    "unavailable_reason": surrogate.get(
                        "unavailable_reason",
                        "surrogate_validation_failed",
                    ),
                    "percentiles": None,
                    "probabilities": {},
                    "distribution": None,
                    "rankings": [],
                }
            )
            continue
        values = output_samples[role]
        sorted_values = sorted(values)
        benchmark = benchmarks.get(role)
        probabilities: dict[str, float] = {}
        if role in {"project_irr", "equity_irr"} and benchmark is not None:
            probabilities["above_hurdle"] = sum(
                value > benchmark for value in values
            ) / trial_count
        if role in {"project_npv", "equity_npv"}:
            probabilities["positive"] = sum(
                value > 0 for value in values
            ) / trial_count
        if role == "minimum_dscr" and benchmark is not None:
            breach = sum(value < benchmark for value in values) / trial_count
            probabilities["below_covenant"] = breach
            probabilities["covenant_breach"] = breach
        correlations = [
            {
                "parameter_id": parameter_id,
                "label": labels_by_parameter[parameter_id],
                "correlation": _pearson(samples, values),
            }
            for parameter_id, samples in input_samples.items()
        ]
        correlation_total = sum(
            abs(float(item["correlation"])) for item in correlations
        )
        rankings = sorted(
            [
                {
                    **item,
                    "contribution": (
                        abs(float(item["correlation"]))
                        / correlation_total
                        if correlation_total
                        else 0.0
                    ),
                }
                for item in correlations
            ],
            key=lambda item: (
                -abs(float(item["correlation"])),
                str(item["parameter_id"]),
            ),
        )
        metrics.append(
            {
                "role": role,
                "label": str(surrogate.get("label", role)),
                "availability_status": "available",
                "unavailable_reason": None,
                "percentiles": {
                    "p10": _percentile(sorted_values, 0.10),
                    "p50": _percentile(sorted_values, 0.50),
                    "p90": _percentile(sorted_values, 0.90),
                },
                "probabilities": probabilities,
                "distribution": _histogram(values),
                "rankings": rankings,
            }
        )
    return {
        "method_version": MONTE_CARLO_METHOD_VERSION,
        "trial_count": trial_count,
        "random_seed": random_seed,
        "metrics": metrics,
    }
