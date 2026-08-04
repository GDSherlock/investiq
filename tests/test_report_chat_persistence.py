from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import uuid

import pytest
from sqlalchemy import delete, func, select

from apps.api.app import model_extraction_models  # noqa: F401
from apps.api.app.database import Base
from apps.api.app.model_extraction_models import ModelVersion, WorkbookVersion
from apps.api.app.report_chat_models import (
    ReportChatMessageRecord,
    ReportChatThreadRecord,
)
from apps.api.app.report_chat_repository import ReportChatRepository
from tests.model_extraction_test_support import create_sqlite_session_factory


GRAPH_ID = str(uuid.uuid4())
RUN_ID = str(uuid.uuid4())


@pytest.fixture
def persistence_context():
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    workbook = WorkbookVersion(
        id=str(uuid.uuid4()),
        sha256="a" * 64,
        original_filename="report-model.xlsx",
        storage_type="database",
        storage_ref="database:report-model",
        content_bytes=b"workbook",
        file_size=8,
    )
    model = ModelVersion(
        id=str(uuid.uuid4()),
        workbook_version_id=workbook.id,
        upload_filename="report-model.xlsx",
        status="materialized",
        validation_status="validated",
        submitted=True,
    )
    session.add_all([workbook, model])
    session.commit()
    try:
        yield session, model
    finally:
        session.close()
        engine.dispose()


def _append_user(
    repository: ReportChatRepository,
    thread_id: str,
    *,
    persona_id: str = "IM",
    text: str = "Generate an Investment Committee Paper",
    idempotency_key: str = "message-1",
):
    return repository.append_user_message(
        thread_id=thread_id,
        persona_id=persona_id,
        text=text,
        graph_version_id=GRAPH_ID,
        calculation_run_id=RUN_ID,
        idempotency_key=idempotency_key,
    )


def test_personas_share_one_thread_for_owner_and_model(persistence_context) -> None:
    session, model = persistence_context
    repository = ReportChatRepository(session)
    first = repository.get_or_create_thread(model.id, "client:abc")
    second = repository.get_or_create_thread(model.id, "client:abc")

    assert first.id == second.id

    _append_user(repository, first.id)
    _append_user(
        repository,
        first.id,
        persona_id="CF",
        text="Generate a CFO Funding Note",
        idempotency_key="message-2",
    )

    assert [row.persona_id for row in repository.list_messages(first.id)] == [
        "IM",
        "CF",
    ]


def test_different_owners_do_not_share_a_thread(persistence_context) -> None:
    session, model = persistence_context
    repository = ReportChatRepository(session)

    first = repository.get_or_create_thread(model.id, "client:abc")
    second = repository.get_or_create_thread(model.id, "client:def")

    assert first.id != second.id


def test_duplicate_idempotency_key_returns_existing_user_message(
    persistence_context,
) -> None:
    session, model = persistence_context
    repository = ReportChatRepository(session)
    thread = repository.get_or_create_thread(model.id, "client:abc")

    first, first_created = _append_user(repository, thread.id)
    duplicate, duplicate_created = _append_user(
        repository,
        thread.id,
        persona_id="CF",
        text="This retry must not overwrite the original",
    )

    assert first_created is True
    assert duplicate_created is False
    assert duplicate.id == first.id
    assert duplicate.persona_id == "IM"
    assert duplicate.content_json == {
        "kind": "text",
        "text": "Generate an Investment Committee Paper",
    }


def test_assistant_response_is_linked_and_idempotent(persistence_context) -> None:
    session, model = persistence_context
    repository = ReportChatRepository(session)
    thread = repository.get_or_create_thread(model.id, "client:abc")
    user_message, _created = _append_user(repository, thread.id)
    content = {"kind": "text", "text": "The report is ready."}

    first = repository.append_assistant_message(
        user_message_id=user_message.id,
        persona_id="IM",
        content=content,
        graph_version_id=GRAPH_ID,
        calculation_run_id=RUN_ID,
    )
    duplicate = repository.append_assistant_message(
        user_message_id=user_message.id,
        persona_id="IM",
        content={"kind": "error", "text": "Must not replace first response"},
        graph_version_id=GRAPH_ID,
        calculation_run_id=RUN_ID,
    )

    assert first.response_to_message_id == user_message.id
    assert duplicate.id == first.id
    assert repository.find_response(user_message.id).id == first.id
    assert repository.get_message(thread.id, first.id).content_json == content


def test_history_orders_equal_timestamps_by_message_id(persistence_context) -> None:
    session, model = persistence_context
    repository = ReportChatRepository(session)
    thread = repository.get_or_create_thread(model.id, "client:abc")
    first, _created = _append_user(repository, thread.id)
    second, _created = _append_user(
        repository,
        thread.id,
        persona_id="CF",
        text="Generate a CFO Funding Note",
        idempotency_key="message-2",
    )
    shared_time = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
    first.created_at = shared_time
    second.created_at = shared_time
    session.commit()

    assert [row.id for row in repository.list_messages(thread.id)] == sorted(
        [first.id, second.id]
    )


def test_deleting_thread_cascades_to_messages(persistence_context) -> None:
    session, model = persistence_context
    repository = ReportChatRepository(session)
    thread = repository.get_or_create_thread(model.id, "client:abc")
    _append_user(repository, thread.id)

    session.execute(
        delete(ReportChatThreadRecord).where(ReportChatThreadRecord.id == thread.id)
    )
    session.commit()

    assert session.scalar(select(func.count()).select_from(ReportChatMessageRecord)) == 0


def test_report_chat_migration_has_required_identity_constraints() -> None:
    migration = Path(
        "apps/api/alembic/versions/20260804_0010_persona_report_chat.py"
    ).read_text()

    assert 'revision: str = "20260804_0010"' in migration
    assert 'down_revision: Union[str, Sequence[str], None] = "20260728_0009"' in migration
    assert '"report_chat_threads"' in migration
    assert '"report_chat_messages"' in migration
    assert 'name="uq_report_chat_threads_model_owner"' in migration
    assert 'name="uq_report_chat_messages_thread_idempotency"' in migration
    assert 'ondelete="CASCADE"' in migration
