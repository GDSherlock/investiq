"""Safely diagnose one Azure OpenAI v1 Responses API connection."""

from __future__ import annotations

import os
import sys

import httpx
import openai
from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)


def _print_error(error: Exception, api_key: str) -> None:
    response = getattr(error, "response", None)
    message = str(error).replace(api_key, "<redacted>")
    print("http_status:", getattr(response, "status_code", None))
    print("exception_type:", type(error).__name__)
    print("error_message:", message)
    print("request_id:", getattr(error, "request_id", None))


def main() -> int:
    load_dotenv(override=True)

    try:
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/") + "/"
        api_key = os.environ["AZURE_OPENAI_API_KEY"]
        deployment = os.environ["AZURE_OPENAI_GPT_DEPLOYMENT"]
    except KeyError as error:
        print("http_status:", None)
        print("exception_type:", "ConfigurationError")
        print("error_message:", f"Missing required environment variable: {error.args[0]}")
        print("request_id:", None)
        return 2

    api_version = os.getenv("AZURE_OPENAI_API_VERSION")
    print("endpoint:", repr(endpoint))
    print("deployment:", repr(deployment))
    print("api_version:", repr(api_version))
    print("api_key_loaded:", bool(api_key))
    print("openai_sdk_version:", openai.__version__)

    def log_request_url(request: httpx.Request) -> None:
        print("request_url:", repr(str(request.url)))

    http_client = httpx.Client(event_hooks={"request": [log_request_url]})
    client = OpenAI(
        base_url=endpoint,
        api_key=api_key,
        http_client=http_client,
        max_retries=0,
    )
    try:
        response = client.responses.create(
            model=deployment,
            input="Reply with exactly: CONNECTION_OK",
        )
    except AuthenticationError as error:
        _print_error(error, api_key)
    except PermissionDeniedError as error:
        _print_error(error, api_key)
    except NotFoundError as error:
        _print_error(error, api_key)
    except RateLimitError as error:
        _print_error(error, api_key)
    except APITimeoutError as error:
        _print_error(error, api_key)
    except APIConnectionError as error:
        _print_error(error, api_key)
    except APIStatusError as error:
        _print_error(error, api_key)
    else:
        print("output_text:", response.output_text)
        return 0
    finally:
        http_client.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
