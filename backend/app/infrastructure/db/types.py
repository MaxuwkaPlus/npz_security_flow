from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Dialect, String, TypeDecorator
from sqlalchemy.orm import mapped_column


class UtcDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetime в UTC. SQLite не хранит зону, поэтому нормализуем сами."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Ожидается timezone-aware datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


def new_uuid() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


# Общие типы колонок: UUID хранится канонической строкой, конфигурации — JSON-текстом.
UuidStr = Annotated[str, mapped_column(String(36))]
Code = Annotated[str, mapped_column(String(64))]
Name = Annotated[str, mapped_column(String(200))]
JsonDict = Annotated[dict[str, Any], mapped_column(JSON, default=dict)]
Timestamp = Annotated[datetime, mapped_column(UtcDateTime, default=utcnow)]
