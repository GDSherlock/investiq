from pathlib import Path

from apps.api.app.main import app


ROOT = Path(__file__).parents[1]


def test_monitor_api_surfaces_are_removed() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/investments/{investment_id}/monitor" not in paths
    assert "/api/v1/scenarios/{scenario_id}/monitor" not in paths


def test_deployment_lists_drop_monitor_but_keep_azure_monitor() -> None:
    shell = (ROOT / "infra/deploy.sh").read_text()
    powershell = (ROOT / "infra/deploy.ps1").read_text()
    assert '"monitor" "report"' not in shell
    assert '"monitor", "report"' not in powershell
    assert "az monitor log-analytics" in shell
    assert "az monitor log-analytics" in powershell
    assert (ROOT / "libs/tools/dscr_monitor.py").exists()
