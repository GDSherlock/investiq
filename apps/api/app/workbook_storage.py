"""Provider-neutral immutable workbook storage port and database adapter."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from .model_extraction_models import WorkbookVersion
from .model_extraction_types import WorkbookIntegrityError, WorkbookVersionNotFound


@dataclass(frozen=True)
class WorkbookStorageLocation:
    storage_type: str
    storage_ref: str


class WorkbookStorage(Protocol):
    def location_for(self, storage_key: str) -> WorkbookStorageLocation:
        raise NotImplementedError

    def store_if_absent(
        self,
        location: WorkbookStorageLocation,
        content_bytes: bytes,
        expected_sha256: str,
    ) -> None:
        raise NotImplementedError

    def load(self, location: WorkbookStorageLocation) -> bytes:
        raise NotImplementedError

    def verify(
        self,
        location: WorkbookStorageLocation,
        expected_sha256: str,
        expected_size: int,
    ) -> None:
        raise NotImplementedError


class DatabaseWorkbookStorage:
    """Store immutable workbook bytes in the workbook catalog transaction."""

    storage_type = "database"

    def __init__(self, session: Session):
        self._session = session

    def location_for(self, storage_key: str) -> WorkbookStorageLocation:
        return WorkbookStorageLocation(self.storage_type, storage_key)

    def store_if_absent(
        self,
        location: WorkbookStorageLocation,
        content_bytes: bytes,
        expected_sha256: str,
    ) -> None:
        payload = bytes(content_bytes)
        if sha256(payload).hexdigest() != expected_sha256:
            raise WorkbookIntegrityError("Workbook content SHA-256 does not match expected digest")

        workbook_version = self._find_version(location)
        if workbook_version is None:
            raise WorkbookVersionNotFound("Workbook storage location was not cataloged")

        if workbook_version.content_bytes is None:
            workbook_version.content_bytes = payload
        elif bytes(workbook_version.content_bytes) != payload:
            raise WorkbookIntegrityError("Workbook storage location contains conflicting content")

        if workbook_version.sha256 != expected_sha256:
            raise WorkbookIntegrityError("Workbook catalog SHA-256 conflicts with stored content")
        self._verify_payload(payload, workbook_version.sha256, workbook_version.file_size)

    def load(self, location: WorkbookStorageLocation) -> bytes:
        workbook_version = self._find_version(location)
        if workbook_version is None:
            raise WorkbookVersionNotFound("Workbook storage location was not found")
        if workbook_version.content_bytes is None:
            raise WorkbookIntegrityError("Workbook storage location has no database content")

        payload = memoryview(workbook_version.content_bytes).tobytes()
        self._verify_payload(payload, workbook_version.sha256, workbook_version.file_size)
        return payload

    def verify(
        self,
        location: WorkbookStorageLocation,
        expected_sha256: str,
        expected_size: int,
    ) -> None:
        payload = self.load(location)
        self._verify_payload(payload, expected_sha256, expected_size)

    def _find_version(self, location: WorkbookStorageLocation) -> WorkbookVersion | None:
        if location.storage_type != self.storage_type:
            return None

        for pending in self._session.new:
            if (
                isinstance(pending, WorkbookVersion)
                and pending.storage_type == location.storage_type
                and pending.storage_ref == location.storage_ref
            ):
                return pending

        return self._session.scalar(
            select(WorkbookVersion).where(
                WorkbookVersion.storage_type == location.storage_type,
                WorkbookVersion.storage_ref == location.storage_ref,
            )
        )

    @staticmethod
    def _verify_payload(payload: bytes, expected_sha256: str, expected_size: int) -> None:
        if len(payload) != expected_size:
            raise WorkbookIntegrityError("Workbook content size does not match catalog metadata")
        if sha256(payload).hexdigest() != expected_sha256:
            raise WorkbookIntegrityError("Workbook content SHA-256 does not match catalog metadata")
