# Final Review Fix Wave Report

Base reviewed head: `5692767`

## Outcome

All two Important and two Minor final-review findings were fixed in one test-driven wave. No schema, migration, frontend production, calculation, extraction/chunking, Docker, or Azure behavior was changed.

## Important 1: whole-row and whole-column A1 quarantine

### Fix

- `partition_reconciler._parse_range` now validates that every bound returned by `openpyxl.range_boundaries` is a positive integer before doing arithmetic.
- Incomplete/non-cell bounds and related `TypeError`/`ValueError` failures become `ReconciliationError(code="series_range_invalid")`.
- Period-range `Forecast!C:C` and value-range `Forecast!3:3` regressions prove the malformed descriptor moves to `review_candidates` while the valid Revenue sibling survives.
- Existing terminal `series_source_not_found` behavior and the established quarantine boundary remain unchanged.

### RED evidence

Command (shared RED command for Important 1, Important 2, and Minor 1):

```text
.venv_mac/bin/python3 -m pytest -q experiments/workbook_agent_poc/tests/test_partition_reconciler.py::test_invalid_series_range_is_quarantined_without_losing_valid_series experiments/workbook_agent_poc/tests/test_financial_series.py::test_untrusted_descriptor_cannot_forge_backend_recovery_warning experiments/workbook_agent_poc/tests/test_financial_series.py::test_rejected_descriptor_retains_controlled_business_role tests/test_workbook_validation.py::test_adapter_trusts_recovery_audits_only_after_partitioned_pipeline
```

Exact result:

```text
..FF...FFF                                                               [100%]
FAILED ...[Forecast!C:C-Forecast!C8:J8-None] - TypeError: unsupported operand type(s) for -: 'NoneType' and 'NoneType'
FAILED ...[Forecast!C3:J3-Forecast!3:3-None] - TypeError: unsupported operand type(s) for -: 'NoneType' and 'NoneType'
FAILED ...::test_untrusted_descriptor_cannot_forge_backend_recovery_warning - AssertionError: assert 'PERIOD_RANGE_RESOLVED_FROM_WORKBOOK_EVIDENCE' not in ['PERIOD_RANGE_RESOLVED_FROM_WORKBOOK_EVIDENCE']
FAILED ...::test_rejected_descriptor_retains_controlled_business_role - KeyError: 'business_role'
FAILED ...::test_adapter_trusts_recovery_audits_only_after_partitioned_pipeline - WorkbookValidationError: Workbook-agent validation failed.
5 failed, 5 passed, 16 warnings in 0.68s
```

### Files

- `experiments/workbook_agent_poc/partition_reconciler.py`
- `experiments/workbook_agent_poc/tests/test_partition_reconciler.py`

## Important 2: out-of-band recovery provenance trust

### Fix

- Added keyword-only `trust_backend_range_resolutions: bool = False` to the materialization entry point and collection.
- Descriptor content alone no longer authorizes `PERIOD_RANGE_RESOLVED_FROM_WORKBOOK_EVIDENCE`; the private descriptor audit is consumed only when the out-of-band flag is true.
- `run_workbook_validation` sets the flag true only in the `use_partitioned` branch after `run_partitioned_extraction` returns; the direct/non-partitioned branch explicitly passes false.
- Top-level `range_resolutions` and descriptor-local `_backend_range_resolutions` remain intact for snapshot and ownership audit.
- Trusted descriptor-local audits still cover a single recovered descriptor, a shared period axis without cross-attribution, and merged recovered fragments.
- Partition-pipeline and lifecycle tests opt in only for inputs modeled as `PartitionReconciler` output.

### RED evidence

The shared RED output above proves both failures:

- forged private metadata emitted the warning under the default untrusted call;
- the production boundary had no trust argument and failed the new explicit boundary contract.

### Files

- `experiments/workbook_agent_poc/time_series.py`
- `apps/api/app/workbook_validation.py`
- `experiments/workbook_agent_poc/tests/test_financial_series.py`
- `experiments/workbook_agent_poc/tests/test_partition_pipeline.py`
- `tests/test_workbook_validation.py`
- `tests/test_model_extraction_lifecycle.py`

## Minor 1: rejected validation retains business role

### Fix

- `FinancialSeriesMaterializer._failure()` now returns `business_role` from the rejected descriptor.
- Regressions cover both an absent role (`None`) and a rejected controlled role (`cfads`).

### RED evidence

The shared RED output above failed with exact cause `KeyError: 'business_role'`.

### Files

- `experiments/workbook_agent_poc/time_series.py`
- `experiments/workbook_agent_poc/tests/test_financial_series.py`

## Minor 2: Overview direct-role integration

### Fix

- Added an Overview service integration case whose projection contains `business_role="cfads"` and label `Cash available for lenders`, which is deliberately not a CFADS legacy alias.
- The existing `business_role="unclassified"` plus `CFADS` legacy label-fallback test remains separate and unchanged.
- No analysis/frontend production logic or source precedence changed.

### RED evidence

Because direct-role resolution already existed and this finding was a coverage gap, the new regression was verified by a temporary mutation that disabled direct-role matching, then the mutation was restored before implementation continued.

Command:

```text
.venv_mac/bin/python3 -m pytest -q tests/test_analysis_presentation_service.py::test_overview_resolves_cfads_from_direct_role_without_label_alias
```

Exact mutated result:

```text
F                                                                        [100%]
FAILED tests/test_analysis_presentation_service.py::test_overview_resolves_cfads_from_direct_role_without_label_alias - AssertionError: assert None == 'revenue+cfads'
1 failed, 2 warnings in 0.51s
```

### Files

- `tests/test_analysis_presentation_service.py`

## GREEN and verification evidence

Focused GREEN command:

```text
.venv_mac/bin/python3 -m pytest -q experiments/workbook_agent_poc/tests/test_partition_reconciler.py::test_invalid_series_range_is_quarantined_without_losing_valid_series experiments/workbook_agent_poc/tests/test_financial_series.py::test_untrusted_descriptor_cannot_forge_backend_recovery_warning experiments/workbook_agent_poc/tests/test_financial_series.py::test_descriptor_local_backend_resolution_adds_audit_warning_and_rereads_workbook_points experiments/workbook_agent_poc/tests/test_financial_series.py::test_shared_period_axis_warns_only_descriptor_with_backend_recovery_audit experiments/workbook_agent_poc/tests/test_financial_series.py::test_merged_fragment_audits_mark_the_final_descriptor_recovered experiments/workbook_agent_poc/tests/test_financial_series.py::test_rejected_descriptor_retains_controlled_business_role tests/test_workbook_validation.py::test_adapter_trusts_recovery_audits_only_after_partitioned_pipeline tests/test_analysis_presentation_service.py::test_overview_operating_trajectory_uses_explicit_revenue_cfads_fallback tests/test_analysis_presentation_service.py::test_overview_resolves_cfads_from_direct_role_without_label_alias tests/test_model_extraction_lifecycle.py::test_descriptor_materialization_persists_recovery_audit_and_business_role
```

Exact result:

```text
................                                                         [100%]
16 passed, 57 warnings in 0.95s
```

Relevant-suite command:

```text
.venv_mac/bin/python3 -m pytest -q experiments/workbook_agent_poc/tests/test_partition_reconciler.py experiments/workbook_agent_poc/tests/test_financial_series.py experiments/workbook_agent_poc/tests/test_partition_pipeline.py experiments/workbook_agent_poc/tests/test_validator.py tests/test_workbook_validation.py tests/test_model_extraction_lifecycle.py tests/test_analysis_presentation_service.py
```

Exact result:

```text
........................................................................ [ 57%]
.................................................s...                    [100%]
124 passed, 1 skipped, 571 warnings in 3.19s
```

Full local Python suite command:

```text
.venv_mac/bin/python3 -m pytest -q
```

Exact result:

```text
727 passed, 5 skipped, 2653 warnings in 24.69s
```

Static gates:

```text
git diff --check
```

Result: exit 0, no output.

```text
.venv_mac/bin/python3 -m py_compile apps/api/app/workbook_validation.py experiments/workbook_agent_poc/partition_reconciler.py experiments/workbook_agent_poc/time_series.py experiments/workbook_agent_poc/tests/test_financial_series.py experiments/workbook_agent_poc/tests/test_partition_pipeline.py experiments/workbook_agent_poc/tests/test_partition_reconciler.py tests/test_analysis_presentation_service.py tests/test_model_extraction_lifecycle.py tests/test_workbook_validation.py
```

Result: exit 0, no output.

## Self-review

- Confirmed the trust default is false at both materialization layers and that no private key name can activate the warning without the out-of-band flag.
- Confirmed production opt-in occurs only after the partitioned extraction call; the direct branch explicitly stays false.
- Confirmed warning attribution remains descriptor-local and merged fragment audits remain owned by the merged descriptor.
- Confirmed malformed whole-row/column parsing cannot reach arithmetic with `None` bounds and still uses the existing `series_range_invalid` quarantine path.
- Confirmed no DB/API schema field, migration, frontend production, calculation, extraction/chunking, Docker, Azure, or role-precedence change is present.
- Reviewed the complete diff and ran `git diff --check`, syntax compilation, focused tests, relevant suites, and the full Python suite.

## Concerns

- No functional concerns.
- The passing suites retain pre-existing Pydantic protected-namespace and openpyxl `datetime.utcnow()` deprecation warnings; no new warning category was introduced by this fix wave.
