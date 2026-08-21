"""Учётные записи, назначенные роли, сеансы и журнал событий безопасности."""

from datetime import datetime

from sqlalchemy import ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base
from app.infrastructure.db.types import (
    Code,
    JsonDict,
    Name,
    Timestamp,
    UtcDateTime,
    UuidStr,
    new_uuid,
)


class User(Base):
    """Учётная запись участника.

    `username` одновременно служит идентификатором субъекта в журнале прохождений:
    он попадает в `training_sessions.operator_id`, поэтому «свои результаты»
    определяются сравнением строк, а не отдельным справочником соответствий.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    username: Mapped[Code]
    display_name: Mapped[Name]
    password_hash: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("1"))
    created_at: Mapped[Timestamp]
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    roles: Mapped[list["UserRoleAssignment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


class UserRoleAssignment(Base):
    """Выданная роль. Хранится фактом назначения, а не полем в учётной записи:
    отзыв роли и её выдача должны быть видны в аудите по отдельности."""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    user_id: Mapped[UuidStr] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[Code]
    granted_at: Mapped[Timestamp]
    granted_by: Mapped[str | None] = mapped_column(default=None)

    user: Mapped[User] = relationship(back_populates="roles")


class AuthSession(Base):
    """Выданный токен доступа. Хранится только SHA-256 от значения."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        Index("ix_auth_sessions_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    user_id: Mapped[UuidStr] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column()
    issued_at: Mapped[Timestamp]
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)


class SecurityEvent(Base):
    """Журнал событий безопасности для администратора ИБ.

    Отдельная таблица от `session_events`: те описывают ход обучения, эти — доступ.
    Запись неизменяема; исправление оформляется новым событием.

    Адрес клиента намеренно не сохраняется: AGENTS.md ограничивает сбор персональных
    данных минимально необходимыми идентификаторами участника.
    """

    __tablename__ = "security_events"
    __table_args__ = (Index("ix_security_events_occurred_type", "occurred_at", "event_type"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    occurred_at: Mapped[Timestamp]
    event_type: Mapped[Code]
    outcome: Mapped[Code]
    # Кто действовал. Для неудачного входа учётной записи может не быть, поэтому
    # имя сохраняется строкой отдельно от ссылки.
    actor_user_id: Mapped[str | None] = mapped_column(default=None)
    actor_username: Mapped[str | None] = mapped_column(default=None)
    # Над кем или над чем действовали.
    target_type: Mapped[str | None] = mapped_column(default=None)
    target_id: Mapped[str | None] = mapped_column(default=None)
    request_id: Mapped[str | None] = mapped_column(default=None)
    payload_json: Mapped[JsonDict]
