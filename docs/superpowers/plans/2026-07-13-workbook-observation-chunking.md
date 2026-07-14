# Workbook Observation Chunking Implementation Plan

> **For agentic workers:** Implement inline in this worktree with strict RED to GREEN verification. Do not delegate or modify candidate routing, financial-series logic, persistence, API schemas outside the tool contract, or frontend code.

**Goal:** Replace unsafe observation truncation with runtime-drained, opaque-cursor workbook chunks whose complete observation is enforced by backend coverage.

**Architecture:** `WorkbookToolset.read_range` creates a backend-owned request and returns one JSON-safe rectangular chunk. The runtime follows opaque continuation tokens and gives every complete chunk to the driver before the model can continue. `CoverageTracker` separately records executed and successfully observed chunks, then gates submission from geometric cell coverage and request completeness.

**Tech Stack:** Python, openpyxl, pytest, OpenAI Responses function-calling driver.

## Global Constraints

- Preserve existing worktree changes and keep this task limited to observation, chunking, trace, and coverage tracking.
- Use complete UTF-8 JSON payload size, including all metadata, with safety headroom.
- Prefer row windows and fall back to column windows when one full row exceeds the budget.
- Never truncate driver payload strings.
- Use opaque backend tokens bound to workbook version, sheet, requested range, and chunk index.
- Treat `inspect_sheet` as preview only.

### Task 1: Define failing chunk and driver contracts

**Files:**
- Modify: `experiments/workbook_agent_poc/tests/test_azure_driver.py`
- Create: `experiments/workbook_agent_poc/tests/test_observation_chunking.py`

- [ ] Add tests for legal JSON beyond 12,000 source characters, exact final serialized byte budgets, row-first and two-dimensional splitting, opaque token binding, token replay, workbook-version mismatch, small single chunks, and the required Solar PV sheet dimensions.
- [ ] Run the focused tests and confirm failures are caused by the missing chunk protocol and current driver truncation.

### Task 2: Implement opaque cursor chunking

**Files:**
- Modify: `experiments/workbook_agent_poc/workbook_tools.py`
- Modify: `experiments/workbook_agent_poc/extraction_contract.py`

- [ ] Add immutable workbook version hashing and backend request/token state.
- [ ] Partition ranges into complete rectangular chunks using final compact JSON byte size with headroom.
- [ ] Return request/chunk telemetry and validate continuation binding.
- [ ] Run chunk tests to GREEN.

### Task 3: Implement runtime draining and driver protection

**Files:**
- Modify: `experiments/workbook_agent_poc/agent_loop.py`
- Modify: `experiments/workbook_agent_poc/tests/test_agent_loop.py`
- Modify: `experiments/workbook_agent_poc/tests/test_azure_driver.py`

- [ ] Add failing tests proving runtime auto-drains all chunks and records observation only after successful driver delivery.
- [ ] Add batch observation support for Azure Responses input without reusing a function output call incorrectly.
- [ ] Replace truncation with exact serialization and a structured `payload_too_large` final guard; retry read ranges with a smaller tool budget.
- [ ] Run runtime/driver tests to GREEN.

### Task 4: Enforce geometric observation coverage

**Files:**
- Modify: `experiments/workbook_agent_poc/coverage_gate.py`
- Modify: `experiments/workbook_agent_poc/tests/test_coverage.py`
- Modify: `experiments/workbook_agent_poc/run_test_suite.py`

- [ ] Add failing tests for missing final chunks, gaps, duplicate chunks, out-of-order chunks, cross-request token/binding errors, version changes, and preview-only inspection.
- [ ] Track expected, executed, and observed chunk indexes plus deduplicated cell/range coverage.
- [ ] Gate submission on complete requests and complete used-range coverage for every content sheet.
- [ ] Expose per-sheet observation telemetry and update the deterministic mock caller for automatic pagination.
- [ ] Run coverage and PoC tests to GREEN.

### Task 5: Verify scope and workbook evidence

**Files:**
- Modify only if needed for test fixtures: `experiments/workbook_agent_poc/tests/test_observation_chunking.py`

- [ ] Run all workbook-agent tests with the project-compatible Python interpreter and report baseline incompatibilities separately.
- [ ] Run the Solar PV observation report against `/mnt/data/01_solar_pv_project_finance.xlsx` when accessible; otherwise run the same report against the dimension-equivalent synthetic fixture and identify the unavailable mount.
- [ ] Run `git diff --check`, scan for `[:12000]`, and inspect the final diff against the saved initial `git status` boundary.
