# Canonical Sensitivity Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the smallest production slice that turns persisted canonical assumptions and outputs into an interactive, model-driven sensitivity workbench with real recalculation-backed current outputs, tornado endpoints, and a two-way sensitivity matrix.

**Architecture:** Keep the calculation engine and immutable `calculation_runs` as the only execution and case store. First separate incremental-reuse provenance from the business comparison baseline. Then add one bounded orchestration service that composes the existing canonical calculation facade for a current scenario, two one-way endpoints per selected driver, and an optional Cartesian grid. The frontend discovers model-specific assumptions and outputs by canonical UUID, stores only versioned UI selections and decimal-string overrides, and renders the reference layout with the existing theme and Recharts.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, pytest, Next.js 14, React 18, TypeScript 5, Tailwind CSS, Recharts, Node test runner.

## Global Constraints

- Work only in `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.claude/worktrees/Canonical_Output_Audit` on `audit/canonical-output-sensitivity-readiness`.
- Use `/Users/kingjason/PythonProject/KPMG Project/new-infra-proj/.venv_mac/bin/python3` for Python tests.
- Preserve the pre-existing frontend worktree changes in:
  - `apps/ui/src/app/sensitivity/page.tsx`
  - `apps/ui/src/lib/api.ts`
  - `apps/ui/src/lib/calculation-api-types.ts`
  - `apps/ui/src/lib/calculation-logic.test.ts`
  - `apps/ui/src/lib/sensitivity-output-adapter.ts`
- Do not reset, clean, overwrite, or discard unrelated or user-owned changes.
- Use RED→GREEN for every behavioral change: add the smallest failing test, run it and inspect the expected failure, implement, then rerun focused tests.
- Public sensitivity requests use only canonical `parameter_id`, `financial_series_value_id`, and `output_id` UUIDs. Never expose or match on sheet names, cell addresses, labels, or workbook-specific aliases.
- `base_run_id` continues to mean incremental-execution reuse provenance. `comparison_baseline_run_id` is the completed, zero-override business baseline.
- Do not add sensitivity tables or migrations. Existing deterministic `calculation_runs` persist every case.
- Do not extend the legacy `/scenarios/*/sensitivity*` interpolation routes.
- Do not invent values for unsupported, blocked, missing, or unavailable outputs.
- Do not broaden the calculation function registry in this slice. Record measured unsupported-function blockers separately.
- Cap one request at 12 one-way drivers, five row values, five column values, and 50 total generated runs including the current scenario.
- Reload is GET-only. A page mount, focus event, or storage event must not submit a calculation.
- Use the committed design in `docs/superpowers/specs/2026-07-24-canonical-sensitivity-workbench-design.md` as the behavior contract.

## File Responsibility Map

- `apps/api/app/calculation_rules/phase2_repository.py`: exact completed zero-override baseline lookup.
- `apps/api/app/calculation_integration_service.py`: output projection against the true comparison baseline.
- `apps/api/app/model_extraction_read_service.py`: retain mapped financial series whose business role is null and expose them as `unclassified`.
- `apps/api/app/schemas.py`: bounded canonical sensitivity request/response DTOs and `comparison_baseline_run_id`.
- `apps/api/app/calculation_sensitivity_service.py`: current, one-way, and two-way orchestration over existing deterministic calculations.
- `apps/api/app/routers/calculations.py`: one canonical sensitivity endpoint and error translation.
- `tests/test_calculation_output_discovery.py`: null-role series discovery.
- `tests/test_calculation_integration_service.py`: zero-override comparison-baseline semantics.
- `tests/test_calculation_api.py`: HTTP serialization, validation bounds, and structured failures.
- `tests/test_calculation_sensitivity_service.py`: real persisted case execution, deterministic replay, unavailable outputs, and model-specific UUIDs.
- `apps/ui/src/lib/calculation-api-types.ts`: TypeScript sensitivity contracts.
- `apps/ui/src/lib/api.ts`: canonical sensitivity POST.
- `apps/ui/src/lib/calculation-storage.ts`: versioned workbench document and identity-safe restore.
- `apps/ui/src/lib/sensitivity-analysis.ts`: pure input pagination, range/request derivation, default selection, tornado/matrix adapters, and restore helpers.
- `apps/ui/src/lib/sensitivity-output-adapter.ts`: true-baseline metadata and unclassified model output display.
- `apps/ui/src/components/sensitivity/SensitivityAssumptionPanel.tsx`: dynamic assumption controls and driver selection.
- `apps/ui/src/components/sensitivity/SensitivityTornadoChart.tsx`: selected-output one-way chart from real endpoint cases.
- `apps/ui/src/components/sensitivity/SensitivityTwoWayMatrix.tsx`: accessible two-way matrix from real Cartesian cases.
- `apps/ui/src/app/sensitivity/page.tsx`: GET-only bootstrap, debounced orchestration, stale-response guard, persistence, and reference-layout composition.
- `apps/ui/src/lib/calculation-logic.test.ts`: frontend contract and pure-helper tests.

---

### Task 1: True Comparison Baseline and Complete Canonical Output Discovery

**Files:**

- Modify: `apps/api/app/calculation_rules/phase2_repository.py`
- Modify: `apps/api/app/calculation_integration_service.py`
- Modify: `apps/api/app/model_extraction_read_service.py`
- Modify: `apps/api/app/schemas.py`
- Test: `tests/test_calculation_integration_service.py`
- Test: `tests/test_calculation_engine_v2_persistence_schema.py`
- Test: `tests/test_calculation_output_discovery.py`
- Test: `tests/test_calculation_api.py`

**Interfaces:**

```python
class CalculationRunOutputsResponse(_CalculationDTO):
    calculation_run_id: UUIDString
    model_version_id: UUIDString
    graph_version_id: UUIDString
    base_run_id: UUIDString | None = None
    comparison_baseline_run_id: UUIDString
    outputs: list[CalculationRunOutputItem] = Field(default_factory=list)


def find_completed_zero_override_run(
    self,
    model_version_id: str,
    graph_version_id: str,
    *,
    engine_version: str,
    function_registry_version: str,
    semantics_profile: str,
    run_policy_hash: str,
) -> PersistedCalculationRun | None:
    raise NotImplementedError
```

- [ ] **Step 1: Add the multiple-override RED test**

Extend `tests/test_calculation_integration_service.py` with a baseline → override A → override B sequence. Assert:

```python
assert override_b.base_run_id == override_a.calculation_run_id
assert projection.base_run_id == override_a.calculation_run_id
assert (
    projection.comparison_baseline_run_id
    == baseline.calculation_run_id
)
assert scalar.baseline.value.value == "5"
assert scalar.current.value.value == "23"
```

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -p no:cacheprovider -q tests/test_calculation_integration_service.py -k 'multiple_overrides or comparison_baseline'
```

Expected RED: `comparison_baseline_run_id` is absent and the baseline value comes from override A.

- [ ] **Step 2: Add repository, baseline-policy, and null-role discovery RED tests**

Add four explicit tests:

- `test_repository_finds_completed_zero_override_run_with_exact_versions_and_policy`
  persists an ordinary baseline and asserts its exact ID is returned.
- `test_repository_rejects_nonempty_override_from_zero_baseline_lookup`
  corrupt-test updates the row's hash to the empty-override hash while leaving
  `overrides_json` non-empty, then asserts the repository returns `None`.
- `test_projection_requires_zero_override_baseline_with_matching_policy`
  persists only an idempotency-key baseline, creates a default-policy override,
  and asserts `CalculationIntegrationError(code="CALCULATION_BASELINE_NOT_FOUND",
  status_code=409)`.
- `test_discovery_exposes_null_role_series_as_unclassified` sets the fixture
  series role to `None`, reloads definitions, and asserts the matching
  `output_id` has `business_role == "unclassified"`.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -p no:cacheprovider -q tests/test_calculation_engine_v2_persistence_schema.py tests/test_calculation_integration_service.py tests/test_calculation_output_discovery.py -k 'zero_override or matching_policy or null_role'
```

Expected RED: the projector follows `base_run_id`, and discovery filters the null-role series.

- [ ] **Step 3: Implement exact zero-override lookup**

In `phase2_repository.py`, select only completed runs matching:

```python
CalculationRunRecord.model_version_id == model_version_id
CalculationRunRecord.graph_version_id == graph_version_id
CalculationRunRecord.engine_version == engine_version
CalculationRunRecord.function_registry_version == function_registry_version
CalculationRunRecord.semantics_profile == semantics_profile
CalculationRunRecord.normalized_override_hash == canonical_hash([])
CalculationRunRecord.run_policy_hash == run_policy_hash
```

Order deterministically by completed time, creation time, and ID. Reload the selected run and defensively reject it if `run.overrides` is non-empty.

- [ ] **Step 4: Project against the comparison baseline**

In `CalculationIntegrationService.get_run_outputs`:

1. keep `current_run.base_run_id` unchanged;
2. call `find_completed_zero_override_run` with the current run's exact version and policy values;
3. raise:

```python
CalculationIntegrationError(
    "CALCULATION_BASELINE_NOT_FOUND",
    "A completed zero-override calculation with matching versions is required.",
    status_code=409,
    resource_id=current_run.model_version_id,
)
```

when none exists;
4. project every scalar and series point against that run; and
5. return its ID in `comparison_baseline_run_id`.

Remove only `FinancialSeries.business_role.is_not(None)` from output discovery. Keep the existing `row.business_role or "unclassified"` fallback; do not infer a role.

- [ ] **Step 5: Update HTTP fixture expectations**

Add `comparison_baseline_run_id` to backend API assertions. TypeScript
contracts and frontend fixtures are updated together in Task 4 so Task 1 does
not touch the pre-existing frontend worktree changes. Do not reinterpret
`base_run_id`.

- [ ] **Step 6: Verify Task 1 GREEN**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -p no:cacheprovider -q tests/test_calculation_engine_v2_persistence_schema.py tests/test_calculation_integration_service.py tests/test_calculation_output_discovery.py tests/test_calculation_api.py
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 1**

```bash
git add apps/api/app/calculation_rules/phase2_repository.py apps/api/app/calculation_integration_service.py apps/api/app/model_extraction_read_service.py apps/api/app/schemas.py tests/test_calculation_engine_v2_persistence_schema.py tests/test_calculation_integration_service.py tests/test_calculation_output_discovery.py tests/test_calculation_api.py
git commit -m "fix: separate calculation comparison baseline"
```

---

### Task 2: Bounded Canonical Sensitivity Contracts

**Files:**

- Modify: `apps/api/app/schemas.py`
- Create: `tests/test_calculation_sensitivity_service.py`
- Modify: `tests/test_calculation_api.py`

**Request contracts:**

```python
class CalculationSensitivityOverrideRequest(_CalculationDTO):
    target: CalculationOverrideTarget
    value: CalculationNumberValue


class CalculationSensitivityDriverRequest(_CalculationDTO):
    target: CalculationOverrideTarget
    low: CalculationNumberValue
    high: CalculationNumberValue


class CalculationSensitivityAxisRequest(_CalculationDTO):
    target: CalculationOverrideTarget
    values: list[CalculationNumberValue] = Field(min_length=1, max_length=5)


class CalculationSensitivityTwoWayRequest(_CalculationDTO):
    row: CalculationSensitivityAxisRequest
    column: CalculationSensitivityAxisRequest


class CalculationSensitivityRequest(_CalculationDTO):
    graph_version_id: UUIDString
    output_id: UUIDString
    current_overrides: list[CalculationSensitivityOverrideRequest] = Field(
        default_factory=list,
        max_length=500,
    )
    drivers: list[CalculationSensitivityDriverRequest] = Field(
        min_length=1,
        max_length=12,
    )
    two_way: CalculationSensitivityTwoWayRequest | None = None
```

`CalculationSensitivityRequest` must reject:

- duplicate current override targets;
- duplicate one-way driver targets;
- equal low/high values;
- duplicate values on either two-way axis;
- the same target on both two-way axes; and
- `1 + 2 * len(drivers) + row_count * column_count > 50`.

**Response contracts:**

```python
class CalculationSensitivitySelectedOutput(_CalculationDTO):
    output_id: UUIDString
    business_role: str
    label: str
    unit: str | None = None
    scenario: str | None = None
    number_format: str | None = None
    mapping_status: Literal["mapped", "partial", "missing", "static"]
    support_status: str
    availability_status: Literal["available", "partial", "unavailable"]
    baseline: CalculationProjectedValueItem
    current: CalculationProjectedValueItem


class CalculationSensitivityCase(_CalculationDTO):
    input_value: CalculationNumberValue
    calculation_run_id: UUIDString
    output: CalculationProjectedValueItem
    warnings: list[str] = Field(default_factory=list)


class CalculationSensitivityDriverResult(_CalculationDTO):
    target: CalculationOverrideTarget
    low_case: CalculationSensitivityCase
    high_case: CalculationSensitivityCase
    impact: StrictStr | None = None
    warnings: list[str] = Field(default_factory=list)


class CalculationSensitivityTwoWayCell(_CalculationDTO):
    row_value: CalculationNumberValue
    column_value: CalculationNumberValue
    calculation_run_id: UUIDString
    output: CalculationProjectedValueItem
    warnings: list[str] = Field(default_factory=list)


class CalculationSensitivityTwoWayResult(_CalculationDTO):
    row_target: CalculationOverrideTarget
    column_target: CalculationOverrideTarget
    cells: list[CalculationSensitivityTwoWayCell]


class CalculationSensitivityResponse(_CalculationDTO):
    model_version_id: UUIDString
    graph_version_id: UUIDString
    comparison_baseline_run_id: UUIDString
    current_run_id: UUIDString
    selected_output: CalculationSensitivitySelectedOutput
    drivers: list[CalculationSensitivityDriverResult]
    two_way: CalculationSensitivityTwoWayResult | None = None
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 1: Add schema-validation RED tests**

Use valid UUID strings and assert Pydantic rejects every invalid condition above. Also assert extra fields, cell-coordinate-shaped targets, non-number values, `NaN`, and `Infinity` are rejected.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -p no:cacheprovider -q tests/test_calculation_sensitivity_service.py -k contract
```

Expected RED: sensitivity DTOs do not exist.

- [ ] **Step 2: Implement the exact DTOs and validators**

Compare numeric strings with `Decimal`, not `float`. Compare targets through their existing `.identity` property. Keep serialized decimal values unchanged.

- [ ] **Step 3: Add API-bound RED tests**

Post:

```text
/api/v1/models/{model_version_id}/calculation/sensitivity
```

and assert malformed or over-limit requests return FastAPI 422 before service execution. Assert a structured domain failure retains `code`, `message`, `retryable`, and `resource_id`.

- [ ] **Step 4: Verify contract GREEN**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -p no:cacheprovider -q tests/test_calculation_sensitivity_service.py -k contract
```

Expected: all contract tests pass; route-success tests remain RED until Task 3.

---

### Task 3: Real Persisted One-Way and Two-Way Orchestration

**Files:**

- Create: `apps/api/app/calculation_sensitivity_service.py`
- Modify: `apps/api/app/routers/calculations.py`
- Modify: `tests/test_calculation_sensitivity_service.py`
- Modify: `tests/test_calculation_api.py`

**Service contract:**

```python
class CalculationSensitivityService:
    def __init__(
        self,
        session: Session,
        calculation_service: CalculationIntegrationService,
    ) -> None:
        raise NotImplementedError

    def analyze(
        self,
        model_version_id: str,
        request: CalculationSensitivityRequest,
    ) -> CalculationSensitivityResponse:
        raise NotImplementedError
```

**Case semantics:**

- Resolve the required comparison baseline before generating any case.
- Resolve and validate the selected scalar output and every referenced target
  before generating any case. Every target must belong to the model, be
  editable, and have a numeric canonical current value.
- Use the default `CalculationRunPolicy` hash and exact Phase 2 versions for the baseline lookup.
- Build the current run from `current_overrides`.
- Build every endpoint from the current override map with that driver's target replaced by its explicit case value.
- Build every matrix cell from the current override map with both axis targets replaced.
- Call only `CalculationIntegrationService.calculate` and `get_run_outputs`; never call the evaluator directly.
- Select the requested scalar strictly by `output_id`.
- Preserve typed unavailable values.
- Set `impact` to the absolute decimal difference between available numeric high and low endpoints; otherwise set it to null and append a deterministic warning.

- [ ] **Step 1: Add one-way and baseline-preflight RED tests**

With the existing materialized-rule fixture:

1. prepare and calculate the zero-override baseline;
2. request one current override and two explicit driver endpoints;
3. assert current/low/high are completed persisted runs;
4. assert each selected value equals the real engine result; and
5. assert every projection points to the same comparison baseline.

Also assert that no zero-override baseline produces `CALCULATION_BASELINE_NOT_FOUND` before any new run is inserted. Unknown, wrong-model, non-editable, or non-numeric targets must likewise fail before the `calculation_runs` count changes.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -p no:cacheprovider -q tests/test_calculation_sensitivity_service.py -k 'one_way or baseline_preflight'
```

Expected RED: service module is absent.

- [ ] **Step 2: Implement target replacement and output selection helpers**

Implement private helpers with canonical identities:

```python
def _replace_numeric_override(
    current: Sequence[CalculationSensitivityOverrideRequest],
    target: CalculationOverrideTarget,
    value: CalculationNumberValue,
) -> list[CalculationOverrideRequest]:
    raise NotImplementedError


def _selected_scalar(
    projection: CalculationRunOutputsResponse,
    output_id: str,
) -> CalculationRunScalarOutputItem:
    raise NotImplementedError
```

Sort merged overrides by `(target.kind, UUID)` before building `CalculationRequest` so service-level behavior and tests are deterministic. Prevalidate the union of current, driver, row, and column targets through `ModelExtractionReadService.get_calculation_input`. Raise structured 422 errors:

- `INVALID_SENSITIVITY_OUTPUT` for an unknown output or series output;
- `INVALID_SENSITIVITY_TARGET` for a target not in the model;
- `SENSITIVITY_OUTPUT_UNAVAILABLE` only when an operation requires numeric arithmetic; keep the response output itself unavailable.

- [ ] **Step 3: Implement the current scenario and one-way cases**

Use:

```python
CalculationRequest(
    graph_version_id=request.graph_version_id,
    overrides=merged_overrides,
    idempotency_key=None,
)
```

Do not create a baseline automatically. Obtain baseline/current metadata from the current projection and return the selected scalar output's true baseline/current values.

- [ ] **Step 4: Add two-way and deterministic-replay RED tests**

Assert a 3×2 request returns six cells in row-major request order, every cell has its own real run ID, and the engine values match explicit combined overrides. Repeat the identical request and assert all current, endpoint, and cell run IDs are identical.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -p no:cacheprovider -q tests/test_calculation_sensitivity_service.py -k 'two_way or replay'
```

Expected RED: no two-way cells are returned.

- [ ] **Step 5: Implement Cartesian cases and unavailable warnings**

Iterate row values outermost and column values innermost. Keep unavailable cells in the response with their run IDs and typed reasons. Deduplicate warning strings without changing first-seen order.

- [ ] **Step 6: Prove model-specific UUID behavior**

Create a second synthetic project-finance fixture whose parameter and selected output live on different source cells and therefore have different canonical UUIDs. Submit the same sensitivity shape using the second model's IDs. Assert:

```python
assert first_request.drivers[0].target != second_request.drivers[0].target
assert first_response.selected_output.output_id != second_response.selected_output.output_id
assert first_response.drivers[0].low_case.output.value.value == expected_first
assert second_response.drivers[0].low_case.output.value.value == expected_second
```

No service code may mention either model's label or source cell.

- [ ] **Step 7: Add and verify the HTTP endpoint**

Add `get_calculation_sensitivity_service` and:

```python
@router.post(
    "/models/{model_version_id}/calculation/sensitivity",
    response_model=CalculationSensitivityResponse,
)
def analyze_calculation_sensitivity(
    model_version_id: UUID,
    request: CalculationSensitivityRequest,
    service: CalculationSensitivityService = Depends(
        get_calculation_sensitivity_service
    ),
) -> CalculationSensitivityResponse:
    try:
        return service.analyze(str(model_version_id), request)
    except CalculationIntegrationError as error:
        _translate_error(error)
```

Translate `CalculationIntegrationError` through the existing `_translate_error`.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -p no:cacheprovider -q tests/test_calculation_sensitivity_service.py tests/test_calculation_api.py
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit Tasks 2–3**

```bash
git add apps/api/app/schemas.py apps/api/app/calculation_sensitivity_service.py apps/api/app/routers/calculations.py tests/test_calculation_sensitivity_service.py tests/test_calculation_api.py
git commit -m "feat: orchestrate canonical sensitivity cases"
```

---

### Task 4: Frontend Contracts, Storage, and Pure Analysis Helpers

**Files:**

- Modify: `apps/ui/src/lib/calculation-api-types.ts`
- Modify: `apps/ui/src/lib/api.ts`
- Modify: `apps/ui/src/lib/calculation-storage.ts`
- Create: `apps/ui/src/lib/sensitivity-analysis.ts`
- Modify: `apps/ui/src/lib/sensitivity-output-adapter.ts`
- Modify: `apps/ui/src/lib/calculation-logic.test.ts`

**Storage contract:**

```typescript
export const SENSITIVITY_WORKBENCH_VERSION = 1 as const;

export interface SensitivityWorkbenchDocument {
  version: 1;
  modelVersionId: string;
  graphVersionId: string;
  overridesByTarget: Record<string, string>;
  tornadoDriverKeys: string[];
  selectedOutputId: string | null;
  rowDriverKey: string | null;
  columnDriverKey: string | null;
}
```

Canonical target keys are `parameter:<uuid>` or `financial_series_value:<uuid>`. The document is accepted only when version, model UUID, and graph UUID match. Corrupt, stale, or mismatched documents are removed. `clearCalculationArtifacts` removes the workbench document. `persistGraphVersionId` removes it when the stored graph changes.

Add `persistSensitivityRunSelection(storage, response)`. It stores
`response.comparison_baseline_run_id` as the baseline run, removes the
override run when `current_run_id` equals that baseline, and otherwise stores
`current_run_id` as the override. It must never infer either choice from
`base_run_id`.

**Pure helper contracts:**

```typescript
export async function loadAllEditableNumericParameters(
  modelVersionId: string,
  getInputs?: typeof getCalculationInputs,
): Promise<SensitivityAssumption[]>;

export function deriveSliderSpec(
  decimalValue: string,
): { kind: 'range'; min: string; max: string; step: string }
 | { kind: 'number' };

export function selectDefaultSensitivityOutput(
  kpis: SensitivityKpi[],
): string | null;

export function buildSensitivityRequest(
  input: SensitivityRequestBuildInput,
): CalculationSensitivityRequest;
export function buildTornadoRows(
  response: CalculationSensitivityResponse,
  assumptionsByTarget: ReadonlyMap<string, SensitivityAssumption>,
): SensitivityTornadoRow[];
export function buildTwoWayMatrix(
  response: CalculationSensitivityResponse,
  assumptionsByTarget: ReadonlyMap<string, SensitivityAssumption>,
): SensitivityMatrixView | null;
```

- [ ] **Step 1: Add API and pagination RED tests**

Assert:

- `runCalculationSensitivity` posts to the canonical route with the exact request body;
- all input pages are loaded until `next_cursor` is null;
- only `editable === true` and `current_value.value_type === "number"` parameters survive;
- result order is category, label, target UUID; and
- no sheet/cell fields appear.

Run:

```bash
cd apps/ui
npm test
```

Expected RED: API types/helper are absent.

- [ ] **Step 2: Add range, selection, and request RED tests**

Cover:

```typescript
deriveSliderSpec('100')  // 80..120
deriveSliderSpec('-100') // -120..-80
deriveSliderSpec('0.1')  // 0.08..0.12; remains stored decimal
deriveSliderSpec('0')    // numeric text input, no invented relative range
```

Assert output priority is `project_irr`, `equity_irr`, `npv`, then the first available numeric scalar by stable display order. Assert the request:

- contains only canonical targets and decimal strings;
- merges all changed assumptions into `current_overrides`;
- includes at most 12 selected drivers;
- creates explicit `0.8, 0.9, 1.0, 1.1, 1.2` actual axis values around the current non-zero value; and
- omits a two-way request when axes are missing, equal, or still zero.

- [ ] **Step 3: Add storage and GET-only restore RED tests**

Assert:

- a matching version/model/graph document round-trips;
- malformed JSON or mismatched identity is cleared;
- upload/artifact clearing removes the document;
- graph changes remove the document;
- sensitivity-run persistence uses `comparison_baseline_run_id` and
  `current_run_id`, never `base_run_id`;
- an override-run 404 removes only `overrideRunId` and then GETs the baseline run; and
- restore makes no POST request.

- [ ] **Step 4: Implement TypeScript contracts, API, storage, and helpers**

Mirror the backend snake-case payload exactly in `calculation-api-types.ts`. In `api.ts`:

```typescript
export async function runCalculationSensitivity(
  modelVersionId: string,
  request: CalculationSensitivityRequest,
): Promise<CalculationSensitivityResponse> {
  return parseJsonResponse(
    await fetch(
      `${API_BASE}/api/v1/models/${encodeURIComponent(modelVersionId)}/calculation/sensitivity`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify(request),
      },
    ),
  );
}
```

Use finite numeric checks and stable keys; do not parse or generate workbook coordinates.

- [ ] **Step 5: Correct the output adapter**

Add `comparisonBaselineRunId` to `SensitivityOutputView`, set:

```typescript
hasOverride:
  response.calculation_run_id !== response.comparison_baseline_run_id
```

and retain `unclassified` scalar/series outputs instead of filtering them out. Business-role arrays remain display ordering only.

- [ ] **Step 6: Add tornado and matrix adapter RED tests**

Assert tornado rows:

- join driver labels by canonical target key;
- use low/current/high numeric values from the sensitivity response;
- derive signed low/high deltas around current;
- rank by absolute endpoint impact; and
- retain unavailable rows with null deltas and a reason.

Assert matrix rows/cells remain in explicit axis order and unavailable cells are not replaced with zero.

- [ ] **Step 7: Verify frontend helper GREEN**

Run:

```bash
cd apps/ui
npm test
./node_modules/.bin/tsc --noEmit --incremental false -p tsconfig.json
```

Expected: all frontend tests and full typecheck pass.

- [ ] **Step 8: Commit Task 4**

This commit intentionally includes the pre-existing output-viewer files now extended by the feature.

```bash
git add apps/ui/src/lib/calculation-api-types.ts apps/ui/src/lib/api.ts apps/ui/src/lib/calculation-storage.ts apps/ui/src/lib/sensitivity-analysis.ts apps/ui/src/lib/sensitivity-output-adapter.ts apps/ui/src/lib/calculation-logic.test.ts
git commit -m "feat: add canonical sensitivity frontend contracts"
```

---

### Task 5: Interactive Workbench Matching the Reference Hierarchy

**Files:**

- Create: `apps/ui/src/components/sensitivity/SensitivityAssumptionPanel.tsx`
- Create: `apps/ui/src/components/sensitivity/SensitivityTornadoChart.tsx`
- Create: `apps/ui/src/components/sensitivity/SensitivityTwoWayMatrix.tsx`
- Modify: `apps/ui/src/app/sensitivity/page.tsx`
- Modify: `apps/ui/src/lib/calculation-logic.test.ts`

**Page state:**

```typescript
interface WorkbenchState {
  assumptions: SensitivityAssumption[];
  overridesByTarget: Record<string, string>;
  tornadoDriverKeys: string[];
  selectedOutputId: string | null;
  rowDriverKey: string | null;
  columnDriverKey: string | null;
  outputs: CalculationRunOutputsResponse | null;
  analysis: CalculationSensitivityResponse | null;
}
```

- [ ] **Step 1: Add page-structure and forbidden-legacy RED tests**

Assert the source imports the new components and canonical API. Assert it contains no:

- `getModel`;
- `parsed_json`;
- legacy sensitivity route;
- `sheet_name` or `cell_address`;
- project-specific KPI/assumption label map;
- LNG, throughput fee, WACC, or hardcoded IRR value.

Assert the page has dynamic output selection, a driver limit, a reset action, and `comparison_baseline_run_id`.

- [ ] **Step 2: Implement GET-only bootstrap and stale override fallback**

On mount:

1. read model/graph/baseline/override IDs;
2. GET readiness and require the same graph;
3. GET every editable numeric parameter page;
4. read the matching workbench document;
5. GET override outputs first, falling back on a 404 to baseline after removing only the stale override key; and
6. derive default output/drivers/axes only for missing stored selections.

Do not call `runCalculationSensitivity` from bootstrap, visibility, or storage handlers.

- [ ] **Step 3: Build the dynamic assumption panel**

Render categories and every editable numeric assumption on the left. Each row shows canonical label, current formatted value, unit, reset control, and tornado inclusion checkbox.

- Non-zero base: actual-value range input with ±20% bound and derived step.
- Zero base: numeric text input until a non-zero current value exists.
- Percent: display may multiply by 100, but state/request remains the persisted decimal.
- Disable adding a 13th tornado driver and explain the 12-driver cap.
- Reset all removes overrides but does not invent a baseline calculation.

- [ ] **Step 4: Add debounced real analysis with a revision guard**

Only user interaction enables analysis. Debounce for 300–400 ms. Use a monotonically increasing `useRef` request revision:

```typescript
const revision = ++requestRevisionRef.current;
const analysis = await runCalculationSensitivity(modelVersionId, request);
if (revision !== requestRevisionRef.current) return;
const outputs = await getCalculationRunOutputs(analysis.current_run_id);
if (revision !== requestRevisionRef.current) return;
```

Before applying, verify response model and graph IDs. Keep previous charts visible while showing `Recalculating…`. On success, in one guarded block:

1. set the analysis and output projection;
2. call `persistSensitivityRunSelection`, using the response's explicit
   comparison baseline/current run IDs; and
3. persist the versioned workbench document.

- [ ] **Step 5: Build the reference layout with existing design tokens**

Use this hierarchy:

- left: sticky/scrollable `SensitivityAssumptionPanel`;
- top-right: dynamic current output cards;
- center-right: selected-output dropdown and `SensitivityTornadoChart`;
- bottom-left: baseline/current scalar output comparison;
- bottom-right: row/column selectors and `SensitivityTwoWayMatrix`;
- below: every returned canonical time-series card in one dynamic series
  section, including `unclassified` series.

Use the existing dark cards, gold accent, border tokens, typography, and installed Recharts. Do not add assets, icons, or another chart library.

- [ ] **Step 6: Implement tornado and matrix components**

`SensitivityTornadoChart` uses a horizontal Recharts `BarChart` with a visible legend and signed low/high deltas around zero. It must expose an adjacent textual unavailable-state summary.

`SensitivityTwoWayMatrix` uses a semantic HTML table. Color intensity is derived only from available numeric selected-output values. Each cell retains a screen-readable formatted value; unavailable cells display `Unavailable`.

- [ ] **Step 7: Add stale-response and GET-only behavioral tests**

Use the pure revision-gate/helper seam to resolve request 2 before request 1 and assert only request 2 applies. Assert the source does not invoke POST inside the bootstrap effect and that current output reload occurs only after a successful sensitivity response.

- [ ] **Step 8: Verify Task 5 GREEN**

Run:

```bash
cd apps/ui
npm test
./node_modules/.bin/tsc --noEmit --incremental false -p tsconfig.json
npm run build
```

Expected: tests, typecheck, and production build pass.

- [ ] **Step 9: Commit Task 5**

```bash
git add apps/ui/src/app/sensitivity/page.tsx apps/ui/src/components/sensitivity/SensitivityAssumptionPanel.tsx apps/ui/src/components/sensitivity/SensitivityTornadoChart.tsx apps/ui/src/components/sensitivity/SensitivityTwoWayMatrix.tsx apps/ui/src/lib/calculation-logic.test.ts
git commit -m "feat: build dynamic sensitivity workbench"
```

---

### Task 6: Full Verification, Two-Model Acceptance, and Visual QA

**Files:**

- Create: `docs/reports/2026-07-24-canonical-sensitivity-workbench-acceptance.md`
- Modify only if verification exposes a task-scoped defect.

- [ ] **Step 1: Run focused backend and frontend suites**

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -p no:cacheprovider -q tests/test_calculation_output_discovery.py tests/test_calculation_integration_service.py tests/test_calculation_sensitivity_service.py tests/test_calculation_api.py
cd apps/ui
npm test
./node_modules/.bin/tsc --noEmit --incremental false -p tsconfig.json
```

- [ ] **Step 2: Run the full non-PostgreSQL backend suite**

```bash
cd /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.claude/worktrees/Canonical_Output_Audit
PYTHONDONTWRITEBYTECODE=1 /Users/kingjason/PythonProject/KPMG\ Project/new-infra-proj/.venv_mac/bin/python3 -m pytest -p no:cacheprovider -m 'not postgres' -q
```

Expected: no regression from the recorded baseline of `434 passed, 5 deselected`.

- [ ] **Step 3: Run two-model acceptance**

For two fixtures with different canonical assumption/output UUIDs:

1. materialize and prepare;
2. establish a zero-override baseline;
3. list all editable numeric assumptions and scalar outputs;
4. submit one current override;
5. run at least two one-way drivers;
6. run at least a 3×3 two-way grid;
7. reload the returned run IDs; and
8. assert the same request reuses the same run IDs.

Record exact model/graph/baseline/current/case IDs, labels, values, unavailable reasons, and formula blockers. Do not claim unsupported outputs changed.

- [ ] **Step 4: Start the verified local app and perform browser QA**

Use the user's existing browser preference if one is available; otherwise request permission before Playwright. At a fixed desktop viewport:

1. load `/sensitivity`;
2. compare the live page beside the supplied reference image;
3. verify left assumptions, top outputs, tornado, comparison table, matrix, and lower series;
4. move two sliders quickly and confirm only the newest result remains;
5. change selected output and axes;
6. reload and prove GET-only restore;
7. test zero and unavailable controls; and
8. capture a final screenshot.

Fix visible spacing, overflow, labels, borders, chart legibility, and interaction defects found by the comparison. Do not redesign the existing application shell.

- [ ] **Step 5: Write the acceptance report**

The report must include:

- branch and commit provenance;
- initial dirty-file provenance;
- exact test/build commands and outcomes;
- two-model canonical UUID evidence;
- baseline/current/case run-ID evidence;
- deterministic replay evidence;
- browser viewport and interaction checks;
- screenshot path;
- explicit unsupported formula/output limitations; and
- confirmation that no legacy route, label map, cell address, or hardcoded project KPI entered the new path.

- [ ] **Step 6: Run final source audits**

```bash
rg -n "scenarios/.*/sensitivity|parsed_json|sheet_name|cell_address|throughput|LNG|baseIrr|WACC" apps/ui/src/app/sensitivity apps/ui/src/components/sensitivity apps/ui/src/lib/sensitivity-analysis.ts
git diff --check
git status --short
git log --oneline -6
```

Expected: no forbidden implementation match, no whitespace errors, and only intentional task files remain.

- [ ] **Step 7: Commit the acceptance evidence**

```bash
git add docs/reports/2026-07-24-canonical-sensitivity-workbench-acceptance.md
git commit -m "docs: record canonical sensitivity acceptance"
```

- [ ] **Step 8: Request whole-branch code review**

Review the full range from `851f363` to branch HEAD for correctness, scope, security, canonical-contract fidelity, and evidence quality. Resolve all Critical, Important, and valid Minor findings with RED→GREEN tests, then rerun the full verification commands before declaring completion.
