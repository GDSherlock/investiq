"""Typed comparison between calculated results and imported workbook caches."""

from __future__ import annotations

from dataclasses import dataclass

from .evaluator import ScalarValue
from .types import CalculationRuleExtractionConfiguration


@dataclass(frozen=True)
class CachedValueComparison:
    cached_value: ScalarValue | None
    absolute_error: float | None
    relative_error: float | None
    validation_status: str
    cached_value_freshness: str


class CachedValueComparator:
    def __init__(
        self,
        configuration: CalculationRuleExtractionConfiguration | None = None,
    ):
        self._configuration = configuration or CalculationRuleExtractionConfiguration()

    def compare(
        self,
        calculated: ScalarValue | None,
        cached: ScalarValue | None,
        freshness: str,
    ) -> CachedValueComparison:
        if freshness not in {"missing", "unknown", "recalculation_required"}:
            raise ValueError("Unknown cached-value freshness")
        if calculated is None:
            return CachedValueComparison(
                cached,
                None,
                None,
                "execution_error",
                freshness,
            )
        if cached is None:
            return CachedValueComparison(
                None,
                None,
                None,
                "no_cached_value",
                freshness,
            )
        if calculated.kind == "error" or cached.kind == "error":
            matched = (
                calculated.kind == cached.kind == "error"
                and calculated.error_code == cached.error_code
            )
            return CachedValueComparison(
                cached,
                None,
                None,
                "matched" if matched else "mismatched",
                freshness,
            )
        if "date_serial" in {calculated.kind, cached.kind}:
            if calculated.kind != cached.kind:
                return CachedValueComparison(
                    cached,
                    None,
                    None,
                    "not_comparable",
                    freshness,
                )
            calculated_number = calculated.number_value
            cached_number = cached.number_value
            absolute_error = abs(calculated_number - cached_number)
            relative_error = (
                None
                if cached_number == 0
                else absolute_error / abs(cached_number)
            )
            date_only = all(
                value.iso_evidence is not None
                and "T" not in value.iso_evidence
                for value in (calculated, cached)
            )
            matched = (
                calculated_number == cached_number
                if date_only
                else absolute_error <= 1e-9
            )
            return CachedValueComparison(
                cached,
                absolute_error,
                relative_error,
                "matched" if matched else "mismatched",
                freshness,
            )
        if calculated.kind == cached.kind == "number":
            calculated_number = calculated.number_value
            cached_number = cached.number_value
            absolute_error = abs(calculated_number - cached_number)
            relative_error = (
                None
                if cached_number == 0
                else absolute_error / abs(cached_number)
            )
            tolerance = max(
                self._configuration.absolute_tolerance,
                self._configuration.relative_tolerance
                * max(abs(calculated_number), abs(cached_number)),
            )
            return CachedValueComparison(
                cached,
                absolute_error,
                relative_error,
                "matched" if absolute_error <= tolerance else "mismatched",
                freshness,
            )
        if calculated.kind != cached.kind:
            return CachedValueComparison(
                cached,
                None,
                None,
                "not_comparable",
                freshness,
            )
        matched = calculated.value == cached.value
        return CachedValueComparison(
            cached,
            None,
            None,
            "matched" if matched else "mismatched",
            freshness,
        )
