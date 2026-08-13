from apps.api.app.main import app


EXPECTED_API_OPERATIONS = {
    ("GET", "/api/v1/alerts/active"),
    ("WEBSOCKET", "/api/v1/assistant/chat"),
    ("POST", "/api/v1/assistant/chat-persona"),
    ("GET", "/api/v1/audit/{entity_id}"),
    ("POST", "/api/v1/auth/login"),
    ("GET", "/api/v1/auth/me"),
    ("POST", "/api/v1/auth/register"),
    ("GET", "/api/v1/calculation-runs/{calculation_run_id}"),
    ("GET", "/api/v1/calculation-runs/{calculation_run_id}/cash-flow"),
    ("GET", "/api/v1/calculation-runs/{calculation_run_id}/outputs"),
    ("GET", "/api/v1/calculation-runs/{calculation_run_id}/overview"),
    ("GET", "/api/v1/calculation-sensitivity-analyses/{analysis_id}"),
    ("POST", "/api/v1/debt-analysis/upload"),
    ("GET", "/api/v1/debt-analysis/{job_id}/compare"),
    ("GET", "/api/v1/market-data/{series}"),
    ("GET", "/api/v1/models"),
    ("POST", "/api/v1/models/upload"),
    ("GET", "/api/v1/models/{model_id}"),
    ("GET", "/api/v1/models/{model_id}/assumptions"),
    ("POST", "/api/v1/models/{model_id}/parse"),
    (
        "PUT",
        "/api/v1/models/{model_version_id}/analysis-parameters/{parameter_id}",
    ),
    ("GET", "/api/v1/models/{model_version_id}/calculation/inputs"),
    ("GET", "/api/v1/models/{model_version_id}/calculation/outputs"),
    ("POST", "/api/v1/models/{model_version_id}/calculation/prepare"),
    ("GET", "/api/v1/models/{model_version_id}/calculation/readiness"),
    ("POST", "/api/v1/models/{model_version_id}/calculation/sensitivity"),
    ("POST", "/api/v1/models/{model_version_id}/calculations"),
    ("GET", "/api/v1/models/{model_version_id}/diagnostics"),
    ("POST", "/api/v1/models/{model_version_id}/monte-carlo-runs"),
    ("GET", "/api/v1/models/{model_version_id}/monte-carlo-runs"),
    ("GET", "/api/v1/models/{model_version_id}/monte-carlo/inputs"),
    ("GET", "/api/v1/models/{model_version_id}/report-chat"),
    ("POST", "/api/v1/models/{model_version_id}/report-chat/messages"),
    (
        "GET",
        "/api/v1/models/{model_version_id}/report-chat/messages/{message_id}/docx",
    ),
    ("POST", "/api/v1/models/{model_version_id}/reports"),
    ("GET", "/api/v1/models/{model_version_id}/reports"),
    ("GET", "/api/v1/models/{model_version_id}/semantic-bindings"),
    (
        "PUT",
        "/api/v1/models/{model_version_id}/semantic-bindings/{semantic_role}",
    ),
    ("GET", "/api/v1/monte-carlo-runs/{monte_carlo_run_id}"),
    ("POST", "/api/v1/monte-carlo-runs/{monte_carlo_run_id}/cancel"),
    ("GET", "/api/v1/report-runs/{report_id}"),
    ("POST", "/api/v1/reports/generate"),
    ("POST", "/api/v1/reports/persona-generate"),
    ("GET", "/api/v1/reports/{report_id}"),
    ("POST", "/api/v1/scenarios"),
    ("GET", "/api/v1/scenarios/{scenario_id}"),
    ("GET", "/api/v1/scenarios/{scenario_id}/cashflows"),
    ("POST", "/api/v1/scenarios/{scenario_id}/monte-carlo"),
    ("POST", "/api/v1/scenarios/{scenario_id}/sensitivity"),
    ("POST", "/api/v1/scenarios/{scenario_id}/sensitivity/realtime"),
    ("GET", "/health"),
}


def test_public_api_operation_inventory_is_backward_compatible() -> None:
    actual: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        if path != "/health" and not path.startswith("/api/v1"):
            continue
        methods = getattr(route, "methods", None)
        if methods:
            actual.update((method, path) for method in methods)
        else:
            actual.add(("WEBSOCKET", path))
    assert actual == EXPECTED_API_OPERATIONS
