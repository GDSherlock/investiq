from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from openpyxl import Workbook
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sample_workbook_bytes(value: float = 1.0) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Assumptions"
    worksheet["A1"] = "Input"
    worksheet["B1"] = value
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def create_sqlite_session_factory(
    database_url: str = "sqlite+pysqlite:///:memory:",
) -> tuple[Engine, sessionmaker[Session]]:
    engine_kwargs: dict[str, object] = {
        "connect_args": {"check_same_thread": False},
    }
    if database_url.endswith(":memory:"):
        engine_kwargs["poolclass"] = StaticPool

    engine = create_engine(database_url, **engine_kwargs)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def sqlite_session() -> Iterator[Session]:
    from apps.api.app.database import Base
    from apps.api.app import model_extraction_models  # noqa: F401

    engine, session_factory = create_sqlite_session_factory()
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def sqlite_file_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path}"
