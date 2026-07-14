"""
EXPERIMENTAL — isolated. Open-ended-discovery test suite for the workbook agent.

Runs each adversarial fixture through the backend-owned function-calling loop (mock OR
live Azure), validates every candidate deterministically, scores against ground truth,
and checks acceptance thresholds. Writes JSON reports under results/.

Usage:
  .venv_mac/bin/python3 experiments/workbook_agent_poc/run_test_suite.py --driver mock --all
  .venv_mac/bin/python3 experiments/workbook_agent_poc/run_test_suite.py --driver azure --fixture no_assumptions_sheet
  .venv_mac/bin/python3 experiments/workbook_agent_poc/run_test_suite.py --driver azure --all
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
except Exception:
    pass

from workbook_tools import WorkbookToolset
from agent_loop import run_loop, AzureDriver
from coverage_gate import HardCaps
from validator import validate_extraction
from metrics import score_fixture, check_thresholds

HERE = os.path.dirname(os.path.abspath(__file__))
FX = os.path.join(HERE, "fixtures")
RESULTS = os.path.join(HERE, "results")

FIXTURES = ["no_assumptions_sheet", "multilingual", "scenarios_sensitivity", "hidden_named_injection"]


# --------------------------------------------------------------------------
# Deterministic mock driver: simulates a competent explorer to exercise the HARNESS
# (coverage gate, validator, metrics). It reads ground truth to place candidates, and
# deliberately injects role/value errors so validation is actually tested.
# --------------------------------------------------------------------------
class MockModel:
    def __init__(self, gt: dict, tools: WorkbookToolset):
        self.gt = gt
        self._sheet_ranges = {
            sheet["name"]: (
                f"A1:{get_column_letter(sheet['max_col'])}{sheet['max_row']}"
            )
            for sheet in tools.list_sheets()["sheets"]
        }
        self._calls = self._plan()
        self._i = 0

    def _submitted_role(self, gt_role: str) -> str:
        return gt_role  # a competent explorer submits the true role for correct candidates

    def _cand(self, d, *, role=None, value="__keep__", suffix=""):
        sheet, cell = d["source_reference"].split("!")
        rv = d.get("raw_value") if value == "__keep__" else value
        return {"candidate_id": d["source_reference"] + suffix,
                "original_label": d.get("original_label"),
                "submitted_role": role or self._submitted_role(d["role"]),
                "raw_value": rv,
                "source_references": [{"sheet_name": sheet, "cell": cell}]}

    def _submission(self):
        decls = self.gt["declarations"]
        assumptions, params, derived, outputs = [], [], [], []
        for d in decls:
            role = d["role"]
            if role in ("hardcoded_input", "scenario_input"):
                assumptions.append(self._cand(d))
            elif role == "parameter":
                params.append(self._cand(d))
            elif role == "formula_derived_value":
                derived.append(self._cand(d))
            elif role in ("formula_output", "hardcoded_display_output", "sensitivity_output"):
                outputs.append(self._cand(d))
            # metadata/label/injection/selector: a competent explorer does NOT call these assumptions

        # Deliberate errors so the validator is actually exercised:
        def first(pred):
            return next((d for d in decls if pred(d)), None)
        errs = []
        d_der = first(lambda d: d["role"] == "formula_derived_value")
        if d_der:
            errs.append(self._cand(d_der, role="hardcoded_input", suffix="_ERR_derived_as_assume"))
        d_meta = first(lambda d: d["role"] == "metadata")
        if d_meta:
            errs.append(self._cand(d_meta, role="hardcoded_input", suffix="_ERR_meta_as_assume"))
        d_num = first(lambda d: d["role"] == "hardcoded_input" and isinstance(d.get("raw_value"), (int, float)))
        if d_num:
            errs.append(self._cand(d_num, value=(d_num["raw_value"] or 0) + 987654, suffix="_ERR_fabricated"))
        for inj in self.gt.get("injection_cells", []):
            d_inj = first(lambda d: d["source_reference"] == inj)
            if d_inj:
                errs.append(self._cand(d_inj, role="hardcoded_input", suffix="_ERR_injection_as_assume"))
        assumptions += errs

        return {"metadata": [], "all_assumption_candidates": assumptions,
                "parameter_candidates": params, "derived_value_candidates": derived,
                "output_candidates": outputs, "financial_series_candidates": [],
                "scenario_structures": self.gt.get("expected_scenario_structures", []),
                "sensitivity_structures": self.gt.get("expected_sensitivity_drivers", []),
                "unclassified_inputs": [], "review_candidates": [], "coverage_declaration": {}}

    def _plan(self):
        sheets = self.gt["sheets"]
        plan = [{"name": "get_workbook_metadata", "arguments": {}},
                {"name": "list_sheets", "arguments": {}},
                {"name": "inspect_sheet", "arguments": {"sheet_name": sheets[0]}},
                {"name": "read_range", "arguments": {
                    "sheet_name": sheets[0], "cell_range": self._sheet_ranges[sheets[0]]}}]
        for s in sheets[1:]:
            plan.append({"name": "inspect_sheet", "arguments": {"sheet_name": s}})
            plan.append({"name": "read_range", "arguments": {
                "sheet_name": s, "cell_range": self._sheet_ranges[s]}})
        plan.append({"name": "submit_extraction_result", "arguments": {"result": self._submission()}})
        return plan

    def next_tool_call(self, trace):
        if self._i >= len(self._calls):
            return None
        c = self._calls[self._i]
        self._i += 1
        return c

    def observe(self, name, args, result):
        pass


def _load_gt(name):
    with open(os.path.join(FX, f"{name}.truth.json"), encoding="utf-8") as f:
        return json.load(f)


def _tally(results):
    t = {"validated": 0, "validated_null": 0, "reclassified": 0, "review_required": 0, "rejected": 0}
    for r in results:
        t[r["validation_status"]] = t.get(r["validation_status"], 0) + 1
    return t


def run_fixture(name, driver_kind):
    gt = _load_gt(name)
    tools = WorkbookToolset(file_path=os.path.join(FX, f"{name}.xlsx"))
    driver_meta = {}

    if driver_kind == "azure":
        driver = AzureDriver()
        driver_meta["deployment"] = os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT", "gpt-5.4-mini")
    else:
        driver = MockModel(gt, tools)

    t0 = time.monotonic()
    run = run_loop(driver, tools, caps=HardCaps(), verbose=(driver_kind == "azure"))
    runtime = round(time.monotonic() - t0, 2)

    if driver_kind == "azure":
        driver_meta["prompt_tokens"] = driver.usage_prompt
        driver_meta["completion_tokens"] = driver.usage_completion

    results = validate_extraction(tools, run["final_extraction"])
    metrics = score_fixture(gt, results, run["coverage"])
    thresholds = check_thresholds(metrics)
    tally = _tally(results)

    report = {
        "fixture": name,
        "driver": driver_kind,
        "driver_meta": driver_meta,
        "runtime_seconds": runtime,
        "submitted": run["submitted"],
        "stop_reason": run["stop_reason"],
        "coverage": run["coverage"],
        "candidate_count": len(results),
        "candidate_tally": tally,
        "metrics": metrics,
        "thresholds": thresholds,
    }
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, f"{driver_kind}_{name}.json"), "w", encoding="utf-8") as f:
        json.dump({**report, "validation_results": results, "trace": run["trace"]}, f, ensure_ascii=False, indent=2)
    return report


def _print(report):
    m = report["metrics"]; ad = m["assumption_discovery"]; rc = m["role_classification"]
    ig = m["integrity"]; cov = report["coverage"]
    print(f"\n=== {report['fixture']} [{report['driver']}] ===")
    print(f"  submitted={report['submitted']} stop={report['stop_reason']} runtime={report['runtime_seconds']}s "
          f"tool_calls={cov['tool_call_count']} submit_attempts={cov['submit_attempts']} "
          f"coverage_rejections={cov['coverage_rejections']}")
    if report["driver_meta"]:
        print(f"  driver_meta={report['driver_meta']}")
    print(f"  sheets inspected={cov['inspected_sheets']}/{cov['total_sheets']} "
          f"hidden={cov['hidden_sheets_inspected']}/{cov['hidden_sheets_total']} "
          f"candidates={report['candidate_count']} tally={report['candidate_tally']}")
    print(f"  ASSUMPTION  P={ad['precision']} R={ad['recall']} F1={ad['f1']} "
          f"src_ref_acc={ad['source_reference_accuracy']} val_acc={ad['value_accuracy_available']}")
    if ad["missed_refs"]:
        print(f"    missed: {ad['missed_refs']}")
    if ad["spurious_refs"]:
        print(f"    spurious: {ad['spurious_refs']}")
    print(f"  ROLE        acc={rc['role_accuracy_family']} "
          f"formula_as_assume={rc['formula_derived_confirmed_as_assumption']} "
          f"meta_as_assume={rc['metadata_confirmed_as_assumption']} "
          f"output_as_assume={rc['output_confirmed_as_assumption']}")
    print(f"  INTEGRITY   fabricated_detected={ig['fabricated_values_detected']} "
          f"fabricated_accepted={ig['fabricated_values_accepted']} "
          f"cache_to_zero={ig['missing_cache_to_zero_violations']} "
          f"unknown_label_pres={ig['unknown_label_preservation']} "
          f"injection_fail={ig['prompt_injection_compliance_failures']} "
          f"ext_report={ig['external_ref_reporting_rate']}")
    print(f"  COVERAGE    sheet={cov and m['coverage']['sheet_coverage']:.2f} "
          f"hidden={m['coverage']['hidden_sheet_coverage']:.2f} "
          f"material={m['coverage']['material_region_coverage']:.2f} "
          f"output_region={m['coverage']['output_region_coverage']:.2f}")
    verdict = "PASS" if report["thresholds"]["passed"] else "FAIL"
    print(f"  THRESHOLDS: {verdict}")
    if not report["thresholds"]["passed"]:
        for k, v in report["thresholds"]["checks"].items():
            if not v:
                print(f"     FAILED: {k}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver", choices=["mock", "azure"], default="mock")
    ap.add_argument("--fixture", choices=FIXTURES)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    names = FIXTURES if args.all or not args.fixture else [args.fixture]
    reports = []
    for name in names:
        try:
            rep = run_fixture(name, args.driver)
        except Exception as e:
            import traceback
            print(f"\n=== {name} [{args.driver}] ERROR ===\n{traceback.format_exc()}")
            reports.append({"fixture": name, "error": str(e)})
            continue
        _print(rep)
        reports.append(rep)

    passed = sum(1 for r in reports if r.get("thresholds", {}).get("passed"))
    print(f"\n{'='*60}\nSUITE [{args.driver}]: {passed}/{len(names)} fixtures passed thresholds")
    with open(os.path.join(RESULTS, f"{args.driver}_summary.json"), "w", encoding="utf-8") as f:
        json.dump([{k: v for k, v in r.items() if k not in ("validation_results", "trace")} for r in reports],
                  f, ensure_ascii=False, indent=2)
    if passed != len(names):
        sys.exit(1)


if __name__ == "__main__":
    main()
