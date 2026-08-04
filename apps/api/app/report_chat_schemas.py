"""Validated contracts for persona report conversations."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from .schemas import UUIDString


PersonaId = Literal["IM", "CF", "BD", "FA", "PO"]


class _ReportChatDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class HeadingBlock(_ReportChatDTO):
    kind: Literal["heading"]
    level: int = Field(ge=1, le=3)
    text: StrictStr = Field(min_length=1)
    citation_ids: list[StrictStr] = Field(default_factory=list)


class ParagraphBlock(_ReportChatDTO):
    kind: Literal["paragraph"]
    text: StrictStr = Field(min_length=1)
    citation_ids: list[StrictStr] = Field(min_length=1)


class ListBlock(_ReportChatDTO):
    kind: Literal["bullet_list", "numbered_list"]
    items: list[StrictStr] = Field(min_length=1)
    citation_ids: list[StrictStr] = Field(min_length=1)


class TableBlock(_ReportChatDTO):
    kind: Literal["table"]
    columns: list[StrictStr] = Field(min_length=1)
    rows: list[list[StrictStr]] = Field(min_length=1)
    citation_ids: list[StrictStr] = Field(min_length=1)


ReportBlock = Annotated[
    HeadingBlock | ParagraphBlock | ListBlock | TableBlock,
    Field(discriminator="kind"),
]


class ReportCitation(_ReportChatDTO):
    id: StrictStr = Field(pattern=r"^[MU][1-9][0-9]*$")
    source_type: Literal["model", "user"]
    label: StrictStr = Field(min_length=1)
    source_ref: StrictStr = Field(min_length=1)
    message_id: UUIDString | None = None


class ReportDocument(_ReportChatDTO):
    title: StrictStr = Field(min_length=1)
    blocks: list[ReportBlock] = Field(min_length=1)
    citations: list[ReportCitation] = Field(default_factory=list)


class ReportChatAssistantContent(_ReportChatDTO):
    kind: Literal["text", "report"]
    text: StrictStr | None = None
    report: ReportDocument | None = None

    @model_validator(mode="after")
    def require_matching_content(self) -> Self:
        if self.kind == "text":
            if not self.text:
                raise ValueError("Text assistant content requires text.")
            if self.report is not None:
                raise ValueError("Text assistant content cannot include a report.")
        elif self.report is None:
            raise ValueError("Report assistant content requires a report.")
        elif self.text is not None:
            raise ValueError("Report assistant content cannot include text.")
        return self


class ReportChatMessageCreateRequest(_ReportChatDTO):
    client_id: UUIDString
    graph_version_id: UUIDString
    calculation_run_id: UUIDString
    persona_id: PersonaId
    message: StrictStr = Field(min_length=1, max_length=20_000)
    idempotency_key: StrictStr = Field(min_length=1, max_length=128)


class ReportChatMessageResponse(_ReportChatDTO):
    message_id: UUIDString
    thread_id: UUIDString
    role: Literal["user", "assistant", "system"]
    kind: Literal["text", "report", "error"]
    persona_id: PersonaId
    text: StrictStr | None = None
    report: ReportDocument | None = None
    graph_version_id: UUIDString
    calculation_run_id: UUIDString
    created_at: datetime

    @model_validator(mode="after")
    def require_matching_content(self) -> Self:
        if self.kind in {"text", "error"}:
            if not self.text:
                raise ValueError("Text and error messages require text.")
            if self.report is not None:
                raise ValueError("Text and error messages cannot include a report.")
        elif self.report is None:
            raise ValueError("Report messages require a report document.")
        elif self.text is not None:
            raise ValueError("Report messages cannot include text.")
        return self


class ReportChatThreadResponse(_ReportChatDTO):
    thread_id: UUIDString | None
    model_version_id: UUIDString
    messages: list[ReportChatMessageResponse]


class ReportChatExchangeResponse(_ReportChatDTO):
    thread_id: UUIDString
    user_message: ReportChatMessageResponse
    assistant_message: ReportChatMessageResponse
