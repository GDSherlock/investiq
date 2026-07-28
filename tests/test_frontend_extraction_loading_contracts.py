import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "apps" / "ui"
PAGE = UI / "src" / "app" / "page.tsx"
GLOBALS = UI / "src" / "app" / "globals.css"
COMPONENTS = UI / "src" / "components" / "extraction"
PROGRESS = UI / "src" / "lib" / "extractionProgress.ts"
ATTEMPT = UI / "src" / "lib" / "uploadAttempt.ts"
API = UI / "src" / "lib" / "api.ts"


def read(path: Path) -> str:
    assert path.exists(), f"missing required frontend file: {path}"
    return path.read_text(encoding="utf-8")


def test_loading_experience_has_focused_component_boundaries() -> None:
    expected = {
        "ExtractionLoadingExperience.tsx",
        "ExtractionStageStepper.tsx",
        "WorkbookTransformation.tsx",
        "ProcessingActivityList.tsx",
    }

    assert expected == {path.name for path in COMPONENTS.glob("*.tsx")}
    assert PROGRESS.exists()
    assert ATTEMPT.exists()


def test_home_upload_uses_one_request_controller_and_existing_api_once() -> None:
    source = read(PAGE)

    assert "createProgressDriver" in source
    assert "runUploadAttempt" in source
    assert "ExtractionLoadingExperience" in source
    assert source.count("uploadWorkbookForCalculation(file)") == 1
    assert "persistUploadIdentity(localStorage, response)" in source
    assert "response.model_version_id" in source
    assert "response.workbook_version_id" in source


def test_home_resets_mounted_guard_during_strict_mode_effect_setup() -> None:
    source = read(PAGE)
    lifecycle_effect = """
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
"""

    assert lifecycle_effect in source


def test_loading_flow_adds_no_backend_pressure_or_fake_cancellation() -> None:
    source = "\n".join(read(path) for path in (PAGE, PROGRESS, ATTEMPT))
    forbidden = (
        "setInterval(",
        "EventSource(",
        "new WebSocket(",
        "/status",
        "Cancel Upload",
    )

    for token in forbidden:
        assert token not in source


def test_loading_copy_is_generic_and_never_uses_the_real_filename() -> None:
    source = "\n".join(read(path) for path in COMPONENTS.glob("*.tsx"))

    assert "Your model" in source
    assert "Financial_Model.xlsx" not in source
    assert "file.name" not in source
    assert "filename" not in source.lower()


def test_reduced_motion_disables_continuous_loading_animation() -> None:
    source = read(GLOBALS)

    assert "@media (prefers-reduced-motion: reduce)" in source
    assert ".extraction-scan" in source
    assert ".extraction-particle" in source
    assert "animation: none" in source


def test_package_keeps_dependencies_and_lint_contract_unchanged() -> None:
    package = json.loads(read(UI / "package.json"))

    assert package["scripts"]["lint"] == "next lint"
    assert package["scripts"]["test"] == (
        "npm run test:calculation && npm run test:loading"
    )
    assert package["scripts"]["test:loading"] == "node --test tests/*.test.cjs"
    assert "api-proxy.test.js" in package["scripts"]["test:calculation"]
    assert "calculation-logic.test.js" in package["scripts"]["test:calculation"]
    assert package["dependencies"] == {
        "next": "^14.2.0",
        "react": "^18.3.0",
        "react-dom": "^18.3.0",
        "recharts": "^2.12.0",
        "undici": "6.24.1",
    }
    assert package["devDependencies"] == {
        "@types/node": "^20.12.0",
        "@types/react": "^18.3.0",
        "@types/react-dom": "^18.3.0",
        "@types/react-test-renderer": "18.3.0",
        "typescript": "^5.4.0",
        "autoprefixer": "^10.4.0",
        "postcss": "^8.4.0",
        "react-test-renderer": "18.3.1",
        "tailwindcss": "^3.4.0",
    }


def test_upload_api_preserves_typed_backend_detail_without_extra_requests() -> None:
    source = read(API)

    assert "parseCalculationApiErrorPayload" in source
    assert "uploadWorkbookForCalculation" in source
    assert source.count("fetch(`${API_BASE}/api/v1/models/upload`") == 1
    assert "readResponsePayload" in source
