from datetime import UTC, datetime
import uuid

import pytest
from pydantic import ValidationError

from apps.api.app.report_personas import get_report_persona
from apps.api.app.report_chat_schemas import (
    ReportChatAssistantContent,
    ReportChatMessageResponse,
    ReportDocument,
)


def test_personas_own_exact_report_types_and_prompts() -> None:
    assert {
        key: (
            get_report_persona(key).report_type,
            get_report_persona(key).primary_prompt,
        )
        for key in ("IM", "CF", "BD", "FA", "PO")
    } == {
        "IM": (
            "Investment Committee Paper",
            "Generate an Investment Committee Paper",
        ),
        "CF": ("CFO Funding Note", "Generate a CFO Funding Note"),
        "BD": ("Board One-Pager", "Generate a Board One-Pager"),
        "FA": (
            "Technical Sensitivity Summary",
            "Generate a Technical Sensitivity Summary",
        ),
        "PO": (
            "Variance and Action Report",
            "Generate a Variance and Action Report",
        ),
    }


def test_report_document_rejects_arbitrary_html_blocks() -> None:
    with pytest.raises(ValidationError):
        ReportDocument.model_validate(
            {
                "title": "Unsafe",
                "blocks": [{"kind": "html", "html": "<script>x</script>"}],
                "citations": [],
            }
        )


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        ({"kind": "text"}, "Text assistant content requires text"),
        ({"kind": "report"}, "Report assistant content requires a report"),
    ],
)
def test_assistant_content_requires_payload_matching_its_kind(
    payload: dict[str, str], expected_message: str
) -> None:
    with pytest.raises(ValidationError, match=expected_message):
        ReportChatAssistantContent.model_validate(payload)


def test_report_message_rejects_report_kind_without_report_document() -> None:
    identifier = str(uuid.uuid4())

    with pytest.raises(
        ValidationError, match="Report messages require a report document"
    ):
        ReportChatMessageResponse.model_validate(
            {
                "message_id": identifier,
                "thread_id": str(uuid.uuid4()),
                "role": "assistant",
                "kind": "report",
                "persona_id": "IM",
                "graph_version_id": str(uuid.uuid4()),
                "calculation_run_id": str(uuid.uuid4()),
                "created_at": datetime.now(UTC),
            }
        )
