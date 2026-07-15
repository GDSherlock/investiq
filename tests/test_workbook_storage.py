from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update

from apps.api.app.database import Base
from apps.api.app.model_extraction_models import WorkbookVersion
from apps.api.app.model_extraction_repository import WorkbookVersionRepository
from apps.api.app.model_extraction_types import WorkbookIntegrityError, json_safe
from apps.api.app.workbook_storage import (
    DatabaseWorkbookStorage,
    WorkbookStorageLocation,
)
from tests.model_extraction_test_support import (
    create_sqlite_session_factory,
    sample_workbook_bytes,
)


@pytest.fixture
def storage_context():
    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    storage = DatabaseWorkbookStorage(session)
    repository = WorkbookVersionRepository(session, storage)
    try:
        yield session, storage, repository
    finally:
        session.close()
        engine.dispose()


def test_database_adapter_round_trips_bytes_through_storage_port(storage_context) -> None:
    session, storage, repository = storage_context
    content = sample_workbook_bytes()
    workbook_version = repository.get_or_create(content, "model.xlsx")
    session.commit()

    location = WorkbookStorageLocation(
        workbook_version.storage_type,
        workbook_version.storage_ref,
    )

    assert storage.load(location) == content
    storage.verify(location, sha256(content).hexdigest(), len(content))


def test_storage_location_is_content_addressed_and_opaque(storage_context) -> None:
    _session, storage, _repository = storage_context
    digest = "a" * 64

    location = storage.location_for(f"workbooks/sha256/{digest}.xlsx")

    assert location == WorkbookStorageLocation(
        storage_type="database",
        storage_ref=f"workbooks/sha256/{digest}.xlsx",
    )
    assert not location.storage_ref.startswith("/")
    assert "://" not in location.storage_ref


def test_identical_bytes_reuse_workbook_version_id(storage_context) -> None:
    session, _storage, repository = storage_context
    content = sample_workbook_bytes()

    first = repository.get_or_create(content, "first.xlsx")
    session.flush()
    second = repository.get_or_create(content, "first.xlsx")

    assert second.id == first.id


def test_identical_bytes_with_new_filename_preserve_first_filename(storage_context) -> None:
    session, _storage, repository = storage_context
    content = sample_workbook_bytes()

    first = repository.get_or_create(content, "first.xlsx")
    session.flush()
    second = repository.get_or_create(content, "renamed.xlsx")

    assert second.id == first.id
    assert second.original_filename == "first.xlsx"


def test_storage_conflict_at_existing_key_raises_integrity_error(storage_context) -> None:
    session, storage, repository = storage_context
    original = sample_workbook_bytes(1.0)
    conflicting = sample_workbook_bytes(2.0)
    workbook_version = repository.get_or_create(original, "model.xlsx")
    session.flush()
    location = WorkbookStorageLocation(
        workbook_version.storage_type,
        workbook_version.storage_ref,
    )

    with pytest.raises(WorkbookIntegrityError, match="conflicting content"):
        storage.store_if_absent(
            location,
            conflicting,
            sha256(conflicting).hexdigest(),
        )


def test_load_rejects_sha_mismatch(storage_context) -> None:
    session, storage, repository = storage_context
    content = sample_workbook_bytes()
    workbook_version = repository.get_or_create(content, "model.xlsx")
    session.commit()
    replacement = b"x" * len(content)
    session.execute(
        update(WorkbookVersion)
        .where(WorkbookVersion.id == workbook_version.id)
        .values(content_bytes=replacement)
    )
    session.commit()

    with pytest.raises(WorkbookIntegrityError, match="SHA-256"):
        storage.load(
            WorkbookStorageLocation(
                workbook_version.storage_type,
                workbook_version.storage_ref,
            )
        )


def test_load_rejects_size_mismatch(storage_context) -> None:
    session, storage, repository = storage_context
    content = sample_workbook_bytes()
    workbook_version = repository.get_or_create(content, "model.xlsx")
    session.commit()
    session.execute(
        update(WorkbookVersion)
        .where(WorkbookVersion.id == workbook_version.id)
        .values(file_size=len(content) + 1)
    )
    session.commit()

    with pytest.raises(WorkbookIntegrityError, match="size"):
        storage.load(
            WorkbookStorageLocation(
                workbook_version.storage_type,
                workbook_version.storage_ref,
            )
        )


def test_repository_never_returns_mutable_content_buffer(storage_context) -> None:
    session, storage, repository = storage_context
    content = sample_workbook_bytes()
    workbook_version = repository.get_or_create(content, "model.xlsx")
    session.flush()

    loaded = storage.load(
        WorkbookStorageLocation(
            workbook_version.storage_type,
            workbook_version.storage_ref,
        )
    )

    assert isinstance(loaded, bytes)
    assert loaded == content
    with pytest.raises(TypeError):
        loaded[0] = 0  # type: ignore[index]


def test_json_safe_preserves_scalar_types_and_encodes_domain_values() -> None:
    identifier = uuid4()
    timestamp = datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc)

    encoded = json_safe(
        {
            "id": identifier,
            "as_of": date(2026, 7, 15),
            "timestamp": timestamp,
            "values": (1, 2.5, True, None),
        }
    )

    assert encoded == {
        "id": str(identifier),
        "as_of": "2026-07-15",
        "timestamp": "2026-07-15T12:30:00+00:00",
        "values": [1, 2.5, True, None],
    }
    assert UUID(encoded["id"]) == identifier
