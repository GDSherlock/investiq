from apps.api.app.main import app


def test_monitor_api_surfaces_are_removed() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/investments/{investment_id}/monitor" not in paths
    assert "/api/v1/scenarios/{scenario_id}/monitor" not in paths
