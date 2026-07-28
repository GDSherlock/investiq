"""Persisted Monte Carlo orchestration over canonical calculation outputs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from time import monotonic
from typing import Any, Mapping, Sequence
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .analysis_output_resolver import (
    resolve_analysis_output,
    resolve_analysis_parameter,
)
from .analysis_models import (
    MonteCarloInputConfigurationRecord,
    MonteCarloResultArtifactRecord,
    MonteCarloRunRecord,
)
from .calculation_integration_service import (
    CalculationIntegrationError,
    CalculationIntegrationService,
)
from .calculation_rules.phase2_models import CalculationRunRecord
from .calculation_rules.phase2_types import (
    PHASE2_ENGINE_VERSION,
    canonical_hash,
)
from .model_extraction_models import ModelParameter
from .monte_carlo_engine import (
    MONTE_CARLO_METHOD_VERSION,
    MonteCarloCancelled,
    simulate_surrogate,
    validate_distribution,
)
from .schemas import (
    CalculationNumberValue,
    CalculationOverrideRequest,
    CalculationRequest,
    MonteCarloEligibleInputItem,
    MonteCarloInputCatalogResponse,
    MonteCarloRunCreateRequest,
    MonteCarloRunHistoryResponse,
    MonteCarloRunResponse,
    ParameterOverrideTarget,
)


_DISTRIBUTIONS = [
    "normal",
    "triangular",
    "uniform",
    "lognormal",
    "discrete",
]
_OUTPUT_ROLES = {
    "project_irr",
    "equity_irr",
    "project_npv",
    "equity_npv",
    "minimum_dscr",
}
_HOLDOUT_ERROR_LIMIT = Decimal("0.05")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _number_from_projected(output: Any) -> Decimal | None:
    projected = output.current
    if (
        projected.availability_status != "available"
        or projected.value is None
        or projected.value.value_type != "number"
    ):
        return None
    return Decimal(projected.value.value)


class MonteCarloService:
    def __init__(
        self,
        session: Session,
        calculation_service: CalculationIntegrationService,
    ) -> None:
        self._session = session
        self._calculation_service = calculation_service

    def input_catalog(
        self,
        model_version_id: str,
    ) -> MonteCarloInputCatalogResponse:
        readiness = self._calculation_service.get_readiness(
            model_version_id
        )
        if readiness.status not in {"ready", "ready_with_warning"}:
            raise CalculationIntegrationError(
                "CALCULATION_NOT_PREPARED",
                "Monte Carlo inputs require a prepared calculation graph.",
                status_code=409,
                resource_id=model_version_id,
            )
        parameters = {
            parameter.id: parameter
            for parameter in self._session.scalars(
                select(ModelParameter)
                .where(ModelParameter.model_version_id == model_version_id)
                .order_by(ModelParameter.id)
            )
        }
        inputs: list[MonteCarloEligibleInputItem] = []
        cursor: str | None = None
        while True:
            page = self._calculation_service.list_inputs(
                model_version_id,
                target_kind="parameter",
                editable_only=True,
                limit=500,
                cursor=cursor,
            )
            if page.graph_version_id != readiness.graph_version_id:
                raise CalculationIntegrationError(
                    "GRAPH_VERSION_MISMATCH",
                    "Monte Carlo inputs changed during catalog loading.",
                    status_code=409,
                    resource_id=model_version_id,
                )
            for candidate in page.inputs:
                if candidate.current_value.value_type != "number":
                    continue
                parameter = parameters.get(candidate.target_id)
                inputs.append(
                    MonteCarloEligibleInputItem(
                        parameter_id=candidate.target_id,
                        business_role=(
                            parameter.business_role
                            if parameter is not None
                            else None
                        ),
                        label=candidate.label,
                        unit=candidate.unit,
                        current_value=candidate.current_value.value,
                    )
                )
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        definitions = self._calculation_service.list_outputs(
            model_version_id
        )
        supported_outputs = [
            role
            for role in sorted(_OUTPUT_ROLES)
            if resolve_analysis_output(
                definitions.outputs,
                role,
                entity_kind="scalar",
            )
            is not None
        ]
        return MonteCarloInputCatalogResponse(
            model_version_id=model_version_id,
            graph_version_id=readiness.graph_version_id,
            inputs=inputs,
            supported_distribution_types=_DISTRIBUTIONS,
            supported_output_roles=supported_outputs,
        )

    def create_run(
        self,
        model_version_id: str,
        request: MonteCarloRunCreateRequest,
    ) -> MonteCarloRunResponse:
        catalog = self.input_catalog(model_version_id)
        if request.graph_version_id != catalog.graph_version_id:
            raise CalculationIntegrationError(
                "GRAPH_VERSION_MISMATCH",
                "Monte Carlo graph does not match the active model graph.",
                status_code=409,
                resource_id=request.graph_version_id,
            )
        baseline = self._require_run(
            request.baseline_calculation_run_id,
            model_version_id,
            request.graph_version_id,
        )
        current = self._require_run(
            request.current_calculation_run_id,
            model_version_id,
            request.graph_version_id,
        )
        if baseline.overrides_json:
            raise CalculationIntegrationError(
                "INVALID_MONTE_CARLO_BASELINE",
                "Monte Carlo baseline must be a zero-override run.",
                status_code=409,
                resource_id=baseline.id,
            )
        if any(
            item.get("target_kind") != "parameter"
            for item in (current.overrides_json or [])
        ):
            raise CalculationIntegrationError(
                "MONTE_CARLO_CURRENT_RUN_UNSUPPORTED",
                "Monte Carlo currently requires parameter-only current overrides.",
                status_code=409,
                resource_id=current.id,
            )
        catalog_by_id = {
            item.parameter_id: item for item in catalog.inputs
        }
        missing_inputs = [
            item.parameter_id
            for item in request.inputs
            if item.parameter_id not in catalog_by_id
        ]
        if missing_inputs:
            raise CalculationIntegrationError(
                "INVALID_MONTE_CARLO_INPUT",
                "Every Monte Carlo input must be an editable numeric "
                "canonical parameter.",
                status_code=422,
                resource_id=missing_inputs[0],
            )
        unsupported_outputs = [
            role
            for role in request.selected_output_roles
            if role not in catalog.supported_output_roles
        ]
        if unsupported_outputs:
            raise CalculationIntegrationError(
                "INVALID_MONTE_CARLO_OUTPUT",
                "Every Monte Carlo output must resolve unambiguously from "
                "the canonical calculation outputs.",
                status_code=422,
                resource_id=model_version_id,
            )

        payload = {
            "model_version_id": model_version_id,
            **request.model_dump(mode="json", exclude={"idempotency_key"}),
        }
        request_hash = canonical_hash(payload)
        existing = self._session.scalar(
            select(MonteCarloRunRecord).where(
                MonteCarloRunRecord.model_version_id == model_version_id,
                MonteCarloRunRecord.idempotency_key
                == request.idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise CalculationIntegrationError(
                    "IDEMPOTENCY_KEY_REUSED",
                    "Idempotency key was already used for a different "
                    "Monte Carlo configuration.",
                    status_code=409,
                    resource_id=existing.id,
                )
            return self.get_run(existing.id)
        equivalent = self._session.scalar(
            select(MonteCarloRunRecord).where(
                MonteCarloRunRecord.request_hash == request_hash
            )
        )
        if equivalent is not None:
            return self.get_run(equivalent.id)

        current_values = {
            str(item["target_id"]): str(item["value"])
            for item in (current.overrides_json or [])
            if item.get("target_kind") == "parameter"
        }
        inputs_json = []
        for item in request.inputs:
            catalog_item = catalog_by_id[item.parameter_id]
            inputs_json.append(
                {
                    "parameter_id": item.parameter_id,
                    "business_role": catalog_item.business_role,
                    "label": catalog_item.label,
                    "unit": catalog_item.unit,
                    "current_value": current_values.get(
                        item.parameter_id,
                        catalog_item.current_value,
                    ),
                    "distribution_type": item.distribution_type,
                    "distribution_parameters": (
                        item.distribution_parameters
                    ),
                }
            )
        run_id = str(uuid.uuid4())
        run = MonteCarloRunRecord(
            id=run_id,
            model_version_id=model_version_id,
            graph_version_id=request.graph_version_id,
            baseline_calculation_run_id=baseline.id,
            current_calculation_run_id=current.id,
            request_hash=request_hash,
            idempotency_key=request.idempotency_key,
            trial_count=request.trial_count,
            random_seed=request.random_seed,
            method_version=MONTE_CARLO_METHOD_VERSION,
            engine_version=PHASE2_ENGINE_VERSION,
            status="queued",
            cancel_requested=False,
        )
        configuration = MonteCarloInputConfigurationRecord(
            id=str(uuid.uuid4()),
            monte_carlo_run_id=run_id,
            inputs_json=inputs_json,
            correlation_matrix_json=request.correlation_matrix,
            selected_output_roles_json=request.selected_output_roles,
        )
        self._session.add(run)
        try:
            self._session.flush()
            self._session.add(configuration)
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self._session.scalar(
                select(MonteCarloRunRecord).where(
                    MonteCarloRunRecord.request_hash == request_hash
                )
            )
            if existing is None:
                raise
            return self.get_run(existing.id)
        return self.get_run(run_id)

    def get_run(self, monte_carlo_run_id: str) -> MonteCarloRunResponse:
        run = self._session.get(MonteCarloRunRecord, monte_carlo_run_id)
        if run is None:
            raise CalculationIntegrationError(
                "MONTE_CARLO_RUN_NOT_FOUND",
                "Monte Carlo run was not found.",
                status_code=404,
                resource_id=monte_carlo_run_id,
            )
        configuration = self._configuration(run.id)
        artifact = self._session.scalar(
            select(MonteCarloResultArtifactRecord).where(
                MonteCarloResultArtifactRecord.monte_carlo_run_id
                == run.id
            )
        )
        return MonteCarloRunResponse(
            monte_carlo_run_id=run.id,
            model_version_id=run.model_version_id,
            graph_version_id=run.graph_version_id,
            baseline_calculation_run_id=(
                run.baseline_calculation_run_id
            ),
            current_calculation_run_id=run.current_calculation_run_id,
            status=run.status,
            trial_count=run.trial_count,
            random_seed=run.random_seed,
            method_version=run.method_version,
            engine_version=run.engine_version,
            runtime_ms=run.runtime_ms,
            cancel_requested=run.cancel_requested,
            input_configuration={
                "inputs": configuration.inputs_json,
                "correlation_matrix": (
                    configuration.correlation_matrix_json
                ),
                "selected_output_roles": (
                    configuration.selected_output_roles_json
                ),
            },
            result_artifact=artifact.result_json if artifact else None,
            error_code=run.error_code,
            error_message=run.error_message,
            created_at=run.created_at,
            completed_at=run.completed_at,
        )

    def history(
        self,
        model_version_id: str,
        *,
        limit: int = 20,
    ) -> MonteCarloRunHistoryResponse:
        if limit < 1 or limit > 100:
            raise CalculationIntegrationError(
                "INVALID_MONTE_CARLO_HISTORY_LIMIT",
                "Monte Carlo history limit must be between one and 100.",
                status_code=422,
                resource_id=model_version_id,
            )
        records = list(
            self._session.scalars(
                select(MonteCarloRunRecord)
                .where(
                    MonteCarloRunRecord.model_version_id
                    == model_version_id
                )
                .order_by(
                    MonteCarloRunRecord.created_at.desc(),
                    MonteCarloRunRecord.id.desc(),
                )
                .limit(limit)
            )
        )
        return MonteCarloRunHistoryResponse(
            model_version_id=model_version_id,
            runs=[self.get_run(record.id) for record in records],
        )

    def cancel_run(
        self,
        monte_carlo_run_id: str,
    ) -> MonteCarloRunResponse:
        run = self._session.get(MonteCarloRunRecord, monte_carlo_run_id)
        if run is None:
            raise CalculationIntegrationError(
                "MONTE_CARLO_RUN_NOT_FOUND",
                "Monte Carlo run was not found.",
                status_code=404,
                resource_id=monte_carlo_run_id,
            )
        if run.status in {"completed", "failed", "cancelled"}:
            return self.get_run(run.id)
        run.cancel_requested = True
        if run.status == "queued":
            run.status = "cancelled"
            run.completed_at = _now()
        self._session.commit()
        return self.get_run(run.id)

    def claim_next(self, worker_id: str) -> str | None:
        query = (
            select(MonteCarloRunRecord)
            .where(
                MonteCarloRunRecord.status == "queued",
                MonteCarloRunRecord.cancel_requested.is_(False),
            )
            .order_by(
                MonteCarloRunRecord.created_at,
                MonteCarloRunRecord.id,
            )
            .limit(1)
        )
        if self._session.bind is not None and (
            self._session.bind.dialect.name == "postgresql"
        ):
            query = query.with_for_update(skip_locked=True)
        run = self._session.scalar(query)
        if run is None:
            self._session.rollback()
            return None
        run.status = "running"
        run.worker_id = worker_id
        run.claimed_at = _now()
        run.started_at = run.started_at or _now()
        self._session.commit()
        return run.id

    def requeue_stale(self, timeout_seconds: int = 900) -> int:
        cutoff = _now() - timedelta(seconds=timeout_seconds)
        stale = list(
            self._session.scalars(
                select(MonteCarloRunRecord).where(
                    MonteCarloRunRecord.status == "running",
                    MonteCarloRunRecord.claimed_at < cutoff,
                )
            )
        )
        for run in stale:
            if run.cancel_requested:
                run.status = "cancelled"
                run.completed_at = _now()
            else:
                run.status = "queued"
                run.worker_id = None
                run.claimed_at = None
        self._session.commit()
        return len(stale)

    def process_claimed(self, monte_carlo_run_id: str) -> None:
        run = self._session.get(MonteCarloRunRecord, monte_carlo_run_id)
        if run is None or run.status != "running":
            return
        started = monotonic()
        try:
            configuration = self._configuration(run.id)
            calibration = self._calibrate(run, configuration)
            if self._is_cancelled(run.id):
                raise MonteCarloCancelled()
            benchmarks = self._benchmarks(
                run.model_version_id,
                run.current_calculation_run_id,
                configuration.selected_output_roles_json,
            )
            result = simulate_surrogate(
                trial_count=run.trial_count,
                random_seed=run.random_seed,
                inputs=configuration.inputs_json,
                correlation_matrix=(
                    configuration.correlation_matrix_json
                ),
                surrogates=calibration["surrogates"],
                benchmarks=benchmarks,
                is_cancelled=lambda: self._is_cancelled(run.id),
            )
            evidence_hash = canonical_hash(
                {
                    "run_id": run.id,
                    "model_version_id": run.model_version_id,
                    "graph_version_id": run.graph_version_id,
                    "baseline_calculation_run_id": (
                        run.baseline_calculation_run_id
                    ),
                    "current_calculation_run_id": (
                        run.current_calculation_run_id
                    ),
                    "configuration": {
                        "inputs": configuration.inputs_json,
                        "correlation_matrix": (
                            configuration.correlation_matrix_json
                        ),
                        "selected_output_roles": (
                            configuration.selected_output_roles_json
                        ),
                    },
                    "calibration": calibration,
                    "result": result,
                }
            )
            self._session.add(
                MonteCarloResultArtifactRecord(
                    id=str(uuid.uuid4()),
                    monte_carlo_run_id=run.id,
                    calibration_json=calibration,
                    result_json={**result, "evidence_hash": evidence_hash},
                    evidence_hash=evidence_hash,
                )
            )
            run.status = "completed"
            run.runtime_ms = int((monotonic() - started) * 1000)
            run.completed_at = _now()
            self._session.commit()
        except MonteCarloCancelled:
            self._session.rollback()
            run = self._session.get(MonteCarloRunRecord, monte_carlo_run_id)
            if run is not None:
                run.status = "cancelled"
                run.cancel_requested = True
                run.runtime_ms = int((monotonic() - started) * 1000)
                run.completed_at = _now()
                self._session.commit()
        except Exception as error:
            self._session.rollback()
            run = self._session.get(MonteCarloRunRecord, monte_carlo_run_id)
            if run is not None:
                run.status = "failed"
                run.error_code = (
                    error.code
                    if isinstance(error, CalculationIntegrationError)
                    else "MONTE_CARLO_PROCESSING_FAILED"
                )
                run.error_message = str(error)
                run.runtime_ms = int((monotonic() - started) * 1000)
                run.completed_at = _now()
                self._session.commit()

    def _calibrate(
        self,
        run: MonteCarloRunRecord,
        configuration: MonteCarloInputConfigurationRecord,
    ) -> dict[str, object]:
        current_projection = self._calculation_service.get_run_outputs(
            run.current_calculation_run_id
        )
        current_outputs = self._numeric_outputs(
            current_projection,
            configuration.selected_output_roles_json,
        )
        centers = {
            str(item["parameter_id"]): Decimal(
                str(item["current_value"])
            )
            for item in configuration.inputs_json
        }
        endpoint_outputs: dict[
            str, dict[str, dict[str, Decimal | None]]
        ] = {}
        case_run_ids: list[str] = []
        for item in configuration.inputs_json:
            if self._is_cancelled(run.id):
                raise MonteCarloCancelled()
            parameter_id = str(item["parameter_id"])
            support = validate_distribution(
                str(item["distribution_type"]),
                item["distribution_parameters"],
            )["support"]
            low, high = Decimal(str(support[0])), Decimal(str(support[1]))
            endpoint_outputs[parameter_id] = {}
            for endpoint, value in (("low", low), ("high", high)):
                calculated = self._calculate_case(
                    run,
                    {parameter_id: value},
                )
                case_run_ids.append(calculated.calculation_run_id)
                projection = self._calculation_service.get_run_outputs(
                    calculated.calculation_run_id
                )
                endpoint_outputs[parameter_id][endpoint] = (
                    self._numeric_outputs(
                        projection,
                        configuration.selected_output_roles_json,
                    )
                )

        surrogates = []
        coefficients_by_role: dict[str, dict[str, Decimal]] = {}
        for role in configuration.selected_output_roles_json:
            intercept = current_outputs.get(role)
            unavailable_reason = None
            coefficients: dict[str, Decimal] = {}
            if intercept is None:
                unavailable_reason = "current_output_unavailable"
            for parameter_id, center in centers.items():
                support = validate_distribution(
                    next(
                        str(item["distribution_type"])
                        for item in configuration.inputs_json
                        if str(item["parameter_id"]) == parameter_id
                    ),
                    next(
                        item["distribution_parameters"]
                        for item in configuration.inputs_json
                        if str(item["parameter_id"]) == parameter_id
                    ),
                )["support"]
                low, high = Decimal(str(support[0])), Decimal(
                    str(support[1])
                )
                low_output = endpoint_outputs[parameter_id]["low"].get(
                    role
                )
                high_output = endpoint_outputs[parameter_id]["high"].get(
                    role
                )
                if (
                    low_output is None
                    or high_output is None
                    or low == high
                ):
                    unavailable_reason = "calibration_endpoint_unavailable"
                    continue
                coefficients[parameter_id] = (
                    high_output - low_output
                ) / (high - low)
            coefficients_by_role[role] = coefficients
            surrogates.append(
                {
                    "role": role,
                    "label": role.replace("_", " ").title(),
                    "intercept": (
                        float(intercept)
                        if intercept is not None
                        else None
                    ),
                    "centers": {
                        key: float(value) for key, value in centers.items()
                    },
                    "coefficients": {
                        key: float(value)
                        for key, value in coefficients.items()
                    },
                    "availability_status": (
                        "available"
                        if unavailable_reason is None
                        and len(coefficients) == len(centers)
                        else "unavailable"
                    ),
                    "unavailable_reason": unavailable_reason,
                    "holdout_relative_error": None,
                }
            )

        holdout_values = {}
        for item in configuration.inputs_json:
            parameter_id = str(item["parameter_id"])
            high = Decimal(
                str(
                    validate_distribution(
                        str(item["distribution_type"]),
                        item["distribution_parameters"],
                    )["support"][1]
                )
            )
            holdout_values[parameter_id] = centers[parameter_id] + (
                high - centers[parameter_id]
            ) / 2
        holdout = self._calculate_case(run, holdout_values)
        case_run_ids.append(holdout.calculation_run_id)
        holdout_projection = self._calculation_service.get_run_outputs(
            holdout.calculation_run_id
        )
        actual_holdout = self._numeric_outputs(
            holdout_projection,
            configuration.selected_output_roles_json,
        )
        for surrogate in surrogates:
            if surrogate["availability_status"] != "available":
                continue
            role = str(surrogate["role"])
            actual = actual_holdout.get(role)
            if actual is None:
                surrogate["availability_status"] = "unavailable"
                surrogate["unavailable_reason"] = (
                    "holdout_output_unavailable"
                )
                continue
            predicted = current_outputs[role] + sum(
                coefficients_by_role[role][parameter_id]
                * (holdout_values[parameter_id] - centers[parameter_id])
                for parameter_id in centers
            )
            relative_error = abs(predicted - actual) / max(
                Decimal("1"),
                abs(actual),
            )
            surrogate["holdout_relative_error"] = float(relative_error)
            if relative_error > _HOLDOUT_ERROR_LIMIT:
                surrogate["availability_status"] = "unavailable"
                surrogate["unavailable_reason"] = (
                    "surrogate_holdout_error_exceeded"
                )
        return {
            "method_version": MONTE_CARLO_METHOD_VERSION,
            "holdout_error_limit": float(_HOLDOUT_ERROR_LIMIT),
            "calculation_run_ids": case_run_ids,
            "surrogates": surrogates,
        }

    def _calculate_case(
        self,
        run: MonteCarloRunRecord,
        parameter_values: Mapping[str, Decimal],
    ):
        current = self._session.get(
            CalculationRunRecord,
            run.current_calculation_run_id,
        )
        overrides = {
            str(item["target_id"]): str(item["value"])
            for item in (current.overrides_json or [])
            if item.get("target_kind") == "parameter"
        }
        overrides.update(
            {
                parameter_id: format(value, "f")
                for parameter_id, value in parameter_values.items()
            }
        )
        return self._calculation_service.calculate(
            run.model_version_id,
            CalculationRequest(
                graph_version_id=run.graph_version_id,
                overrides=[
                    CalculationOverrideRequest(
                        target=ParameterOverrideTarget(
                            kind="parameter",
                            parameter_id=parameter_id,
                        ),
                        value=CalculationNumberValue(
                            value_type="number",
                            value=value,
                        ),
                    )
                    for parameter_id, value in sorted(overrides.items())
                ],
                # Calculation idempotency is already derived from canonical
                # overrides. A per-case key would alter the run-policy hash
                # and make the persisted zero-override baseline incompatible.
                idempotency_key=None,
            ),
        )

    @staticmethod
    def _numeric_outputs(
        projection: Any,
        roles: Sequence[str],
    ) -> dict[str, Decimal | None]:
        values: dict[str, Decimal | None] = {}
        for role in roles:
            output = resolve_analysis_output(
                projection.outputs,
                role,
                entity_kind="scalar",
            )
            values[role] = (
                _number_from_projected(output)
                if output is not None
                else None
            )
        return values

    def _benchmarks(
        self,
        model_version_id: str,
        current_run_id: str,
        roles: Sequence[str],
    ) -> dict[str, float]:
        benchmark_roles = {
            "project_irr": "project_irr_hurdle",
            "equity_irr": "equity_irr_hurdle",
            "minimum_dscr": "dscr_covenant",
        }
        current = self._session.get(CalculationRunRecord, current_run_id)
        overrides = {
            str(item["target_id"]): item["value"]
            for item in (current.overrides_json or [])
            if item.get("target_kind") == "parameter"
        }
        result: dict[str, float] = {}
        parameters = list(
            self._session.scalars(
                select(ModelParameter).where(
                    ModelParameter.model_version_id == model_version_id
                )
            )
        )
        for role in roles:
            benchmark_role = benchmark_roles.get(role)
            if benchmark_role is None:
                continue
            parameter = resolve_analysis_parameter(
                parameters,
                benchmark_role,
            )
            if parameter is None:
                continue
            value = overrides.get(
                parameter.id,
                parameter.validated_value_json,
            )
            try:
                result[role] = float(value)
            except (TypeError, ValueError):
                continue
        return result

    def _require_run(
        self,
        run_id: str,
        model_version_id: str,
        graph_version_id: str,
    ) -> CalculationRunRecord:
        response = self._calculation_service.get_run(run_id)
        record = self._session.get(CalculationRunRecord, run_id)
        if (
            record is None
            or response.model_version_id != model_version_id
            or response.graph_version_id != graph_version_id
            or response.status
            not in {"completed", "completed_with_warning"}
        ):
            raise CalculationIntegrationError(
                "MONTE_CARLO_RUN_IDENTITY_MISMATCH",
                "Baseline and current runs must be completed runs from the "
                "same model and graph.",
                status_code=409,
                resource_id=run_id,
            )
        return record

    def _configuration(
        self,
        monte_carlo_run_id: str,
    ) -> MonteCarloInputConfigurationRecord:
        configuration = self._session.scalar(
            select(MonteCarloInputConfigurationRecord).where(
                MonteCarloInputConfigurationRecord.monte_carlo_run_id
                == monte_carlo_run_id
            )
        )
        if configuration is None:
            raise CalculationIntegrationError(
                "MONTE_CARLO_CONFIGURATION_NOT_FOUND",
                "Monte Carlo input configuration was not found.",
                status_code=500,
                resource_id=monte_carlo_run_id,
            )
        return configuration

    def _is_cancelled(self, monte_carlo_run_id: str) -> bool:
        self._session.expire_all()
        run = self._session.get(MonteCarloRunRecord, monte_carlo_run_id)
        return (
            run is None
            or run.cancel_requested
            or run.status == "cancelled"
        )
