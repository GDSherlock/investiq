"""Regression coverage for Azure OpenAI v1 deployment-script settings."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shell_deploy_script_injects_v1_responses_configuration():
    script = (ROOT / "infra" / "deploy.sh").read_text()

    assert 'GPT_DEPLOYMENT="${GPT_DEPLOYMENT:-gpt-5.4-mini}"' in script
    assert "--model-name gpt-5.4-mini" in script
    assert 'AI_ENDPOINT="${AI_ENDPOINT%/}/openai/v1/"' in script
    assert '"AZURE_OPENAI_API_KEY=${AI_KEY}"' in script
    assert 'AI Key:            ${AI_KEY:-N/A}' not in script


def test_powershell_deploy_script_injects_v1_responses_configuration():
    script = (ROOT / "infra" / "deploy.ps1").read_text()

    assert '$GptDeployment = "gpt-5.4-mini"' in script
    assert "--model-name gpt-5.4-mini" in script
    assert '$AiEndpoint = $AiEndpoint.TrimEnd("/") + "/openai/v1/"' in script
    assert '"AZURE_OPENAI_API_KEY=$AiKey"' in script
    assert 'AI Key:            $AiKey' not in script
