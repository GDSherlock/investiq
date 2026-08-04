from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from apps.api.app.report_chat_docx import ReportChatDocxRenderer, safe_docx_filename
from apps.api.app.report_chat_schemas import ReportDocument


def document_fixture(title: str = "CFO Funding Note") -> ReportDocument:
    return ReportDocument.model_validate(
        {
            "title": title,
            "blocks": [
                {
                    "kind": "heading",
                    "level": 1,
                    "text": "Funding position",
                    "citation_ids": [],
                },
                {
                    "kind": "paragraph",
                    "text": "Project IRR is 12%.",
                    "citation_ids": ["M1"],
                },
                {
                    "kind": "table",
                    "columns": ["Metric", "Value"],
                    "rows": [["Project IRR", "12%"]],
                    "citation_ids": ["M1"],
                },
                {
                    "kind": "bullet_list",
                    "items": ["Monitor the funding headroom"],
                    "citation_ids": ["U1"],
                },
            ],
            "citations": [
                {
                    "id": "M1",
                    "source_type": "model",
                    "label": "Project IRR",
                    "source_ref": "Returns!B12",
                },
                {
                    "id": "U1",
                    "source_type": "user",
                    "label": "User funding assumption",
                    "source_ref": (
                        "message:11111111-1111-4111-8111-111111111111"
                    ),
                    "message_id": "11111111-1111-4111-8111-111111111111",
                },
            ],
        }
    )


def test_docx_preserves_title_table_lists_and_sources() -> None:
    payload = ReportChatDocxRenderer().render(document_fixture())

    with ZipFile(BytesIO(payload)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    assert "CFO Funding Note" in xml
    assert "Funding position" in xml
    assert "Project IRR" in xml
    assert "Monitor the funding headroom" in xml
    assert "[M1]" in xml
    assert "[U1]" in xml
    assert "Evidence Sources" in xml
    assert "Returns!B12" in xml


def test_docx_filename_removes_unsafe_characters() -> None:
    assert safe_docx_filename('../../CFO: Funding/Note?') == "CFO FundingNote.docx"
