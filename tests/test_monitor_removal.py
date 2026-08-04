from pathlib import Path

from apps.api.app.main import app
from apps.orchestrator.engine import AGENT_REGISTRY, IntentType


ROOT = Path(__file__).parents[1]


def test_monitor_api_and_agent_surfaces_are_removed() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/investments/{investment_id}/monitor" not in paths
    assert "/api/v1/scenarios/{scenario_id}/monitor" not in paths
    assert not (ROOT / "apps/api/app/routers/monitor.py").exists()
    assert not (ROOT / "apps/agents/monitor/agent.py").exists()
    assert "monitor" not in {intent.value for intent in IntentType}
    assert "MonitorAgent" not in AGENT_REGISTRY.values()


def test_deployment_lists_drop_monitor_but_keep_azure_monitor() -> None:
    shell = (ROOT / "infra/deploy.sh").read_text()
    powershell = (ROOT / "infra/deploy.ps1").read_text()
    assert '"monitor" "report"' not in shell
    assert '"monitor", "report"' not in powershell
    assert "az monitor log-analytics" in shell
    assert "az monitor log-analytics" in powershell
    assert (ROOT / "libs/tools/dscr_monitor.py").exists()
