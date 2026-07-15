"""Repositories for durable Model Extraction state."""

from __future__ import annotations

from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .model_extraction_models import WorkbookVersion
from .model_extraction_types import WorkbookIntegrityError, new_uuid
from .workbook_storage import WorkbookStorage, WorkbookStorageLocation


class WorkbookVersionRepository:
    """Own workbook identity and catalog metadata without owning byte storage."""

    def __init__(self, session: Session, storage: WorkbookStorage):
        self._session = session
        self._storage = storage

    def get_or_create(
        self,
        content_bytes: bytes,
        original_filename: str,
    ) -> WorkbookVersion:
        payload = bytes(content_bytes)
        if not payload:
            raise WorkbookIntegrityError("Workbook content must not be empty")

        digest = sha256(payload).hexdigest()
        existing = self._session.scalar(
            select(WorkbookVersion).where(WorkbookVersion.sha256 == digest)
        )
        if existing is not None:
            self._verify_existing(existing)
            return existing

        storage_key = f"workbooks/sha256/{digest}.xlsx"
        location = self._storage.location_for(storage_key)
        workbook_version = WorkbookVersion(
            id=new_uuid(),
            sha256=digest,
            original_filename=original_filename,
            storage_type=location.storage_type,
            storage_ref=location.storage_ref,
            file_size=len(payload),
        )

        try:
            with self._session.begin_nested():
                self._session.add(workbook_version)
                self._storage.store_if_absent(location, payload, digest)
                self._session.flush()
        except IntegrityError as exc:
            if not self._is_sha_uniqueness_violation(exc):
                raise
            winner = self._session.scalar(
                select(WorkbookVersion).where(WorkbookVersion.sha256 == digest)
            )
            if winner is None:
                raise
            self._verify_existing(winner)
            return winner

        return workbook_version

    def _verify_existing(self, workbook_version: WorkbookVersion) -> None:
        location = WorkbookStorageLocation(
            workbook_version.storage_type,
            workbook_version.storage_ref,
        )
        self._storage.verify(
            location,
            workbook_version.sha256,
            workbook_version.file_size,
        )

    @staticmethod
    def _is_sha_uniqueness_violation(exc: IntegrityError) -> bool:
        message = str(exc.orig).lower()
        return (
            "uq_workbook_versions_sha256" in message
            or "workbook_versions.sha256" in message
        )
