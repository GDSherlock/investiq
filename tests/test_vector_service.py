"""Regression coverage for the Azure OpenAI v1 embeddings client configuration."""

import importlib

from openai import OpenAI


def test_embedding_client_uses_v1_base_url_and_standard_api_key_name(monkeypatch):
    monkeypatch.setenv(
        "AZURE_OPENAI_ENDPOINT",
        "https://example-resource.services.ai.azure.com/openai/v1/",
    )
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

    from apps.api.app import vector_service

    vector_service = importlib.reload(vector_service)
    client = vector_service._get_client()

    assert type(client) is OpenAI
    assert str(client.base_url) == "https://example-resource.services.ai.azure.com/openai/v1/"


def test_embedding_client_defaults_to_the_deployed_embedding_name(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", raising=False)

    from apps.api.app import vector_service

    vector_service = importlib.reload(vector_service)

    assert vector_service._EMBEDDING_MODEL == "text-embedding-3-small"
