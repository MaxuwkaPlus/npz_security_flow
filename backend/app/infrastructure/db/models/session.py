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

SCHEMA_VERSION = 1


class TrainingSession(Base):
    """Одно прохождение конкретной версии сценария конкретным оператором."""

    __tablename__ = "training_sessions"
    __table_args__ = (
        Index("ix_training_sessions_operator_started", "operator_id", "started_at"),
        Index("ix_training_sessions_active", "status"),
    )

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    operator_id: Mapped[Code]
    instructor_id: Mapped[str | None] = mapped_column(default=None)
    scenario_version_id: Mapped[UuidStr] = mapped_column(ForeignKey("scenario_versions.id"), index=True)
    scenario_level_id: Mapped[UuidStr] = mapped_column(ForeignKey("scenario_levels.id"), index=True)
    scoring_policy_version_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("scoring_policy_versions.id"), index=True
    )
    status: Mapped[Code]
    sim_time_ms: Mapped[int] = mapped_column(default=0)
    # Единый монотонный счётчик сессии: события и снимки нумеруются из него,
    # поэтому клиент по одному sequence_no видит пропуск в любом канале.
    last_sequence_no: Mapped[int] = mapped_column(default=0)
    current_stage_code: Mapped[Code]
    random_seed: Mapped[int]
    # Целевая ветвь, момент и причина возмущения. Никогда не сериализуется в операторский DTO.
    hidden_runtime_config_json: Mapped[JsonDict]
    # Текущее состояние цифрового двойника: из него симуляция продолжается после перезапуска.
    runtime_state_json: Mapped[JsonDict] = mapped_column(default=dict, server_default=text("'{}'"))
    final_outcome: Mapped[str | None] = mapped_column(default=None)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    paused_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    created_at: Mapped[Timestamp]
    # Optimistic locking: клиент может передать ожидаемую версию сессии.
    version_no: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version_no}  # noqa: RUF012 — контракт SQLAlchemy


class SessionEvent(Base):
    """Неизменяемый факт внутри сессии. Исправление выполняется компенсирующим событием."""

    __tablename__ = "session_events"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence_no"),
        Index("ix_session_events_session_sequence", "session_id", "sequence_no"),
    )

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    session_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    sequence_no: Mapped[int]
    sim_time_ms: Mapped[int]
    occurred_at: Mapped[Timestamp]
    event_type: Mapped[Code]
    aggregate_type: Mapped[Code]
    aggregate_id: Mapped[str | None] = mapped_column(default=None)
    payload_json: Mapped[JsonDict]
    causation_id: Mapped[str | None] = mapped_column(default=None)
    correlation_id: Mapped[str | None] = mapped_column(default=None)
    schema_version: Mapped[int] = mapped_column(default=SCHEMA_VERSION)


class ProcessSnapshot(Base):
    """Снимок состояния установки в момент симуляционного времени."""

    __tablename__ = "process_snapshots"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence_no"),
        UniqueConstraint("session_id", "sim_time_ms"),
        Index("ix_process_snapshots_session_sim_time", "session_id", "sim_time_ms"),
    )

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    session_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    sequence_no: Mapped[int]
    sim_time_ms: Mapped[int]
    stage_code: Mapped[Code]
    visible_values_json: Mapped[JsonDict]
    derived_values_json: Mapped[JsonDict]
    # Скрытое состояние двойника: доступно только replay и аудиту.
    internal_state_json: Mapped[JsonDict]
    state_hash: Mapped[Code]
    schema_version: Mapped[int] = mapped_column(default=SCHEMA_VERSION)
    created_at: Mapped[Timestamp]


class SessionStageHistory(Base):
    """История прохождения этапов сценария."""

    __tablename__ = "session_stage_history"
    __table_args__ = (Index("ix_session_stage_history_session_entered", "session_id", "entered_sim_time_ms"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    session_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    stage_code: Mapped[Code]
    entered_sim_time_ms: Mapped[int]
    exited_sim_time_ms: Mapped[int | None] = mapped_column(default=None)
    outcome: Mapped[str | None] = mapped_column(default=None)
    transition_reason_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("session_events.id", ondelete="SET NULL"), default=None
    )


class CommandRequest(Base):
    """Журнал принятых `request_id`: повторный запрос возвращает прежний результат."""

    __tablename__ = "command_requests"

    request_id: Mapped[UuidStr] = mapped_column(primary_key=True)
    session_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    command: Mapped[Code]
    response_json: Mapped[JsonDict]
    created_at: Mapped[Timestamp]

    session: Mapped[TrainingSession] = relationship()


class OperatorAction(Base):
    """Команда оператора. Журнал аудита: принятая команда не переписывается задним числом."""

    __tablename__ = "operator_actions"
    __table_args__ = (Index("ix_operator_actions_session_sim_time", "session_id", "sim_time_ms"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    request_id: Mapped[UuidStr] = mapped_column(unique=True)
    session_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    sequence_no: Mapped[int]
    sim_time_ms: Mapped[int]
    received_at: Mapped[Timestamp]
    action_type: Mapped[Code]
    target_code: Mapped[Code]
    requested_value_json: Mapped[JsonDict]
    before_state_json: Mapped[JsonDict]
    after_state_json: Mapped[JsonDict]
    status: Mapped[Code] = mapped_column(index=True)
    rejection_reason: Mapped[str | None] = mapped_column(default=None)
    # Классификацию correct/ineffective/dangerous выставляет оценка после окна наблюдения.
    classification: Mapped[str | None] = mapped_column(default=None)
    evaluation_pending_until_ms: Mapped[int | None] = mapped_column(default=None)
    expected_rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("expected_action_rules.id", ondelete="SET NULL"), default=None
    )
    requires_verification: Mapped[bool] = mapped_column(default=False)


class SessionAlarm(Base):
    """Экземпляр тревоги в сессии. Снятая тревога остаётся в журнале."""

    __tablename__ = "session_alarms"
    __table_args__ = (Index("ix_session_alarms_session_started", "session_id", "started_sim_time_ms"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    session_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    alarm_rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("alarm_rules.id", ondelete="SET NULL"), default=None
    )
    alarm_code: Mapped[Code] = mapped_column(index=True)
    level: Mapped[Code]
    equipment_code: Mapped[Code]
    message: Mapped[Name]
    ack_required: Mapped[bool] = mapped_column(default=True)
    is_nuisance: Mapped[bool] = mapped_column(default=False)
    started_sim_time_ms: Mapped[int]
    acknowledged_sim_time_ms: Mapped[int | None] = mapped_column(default=None)
    cleared_sim_time_ms: Mapped[int | None] = mapped_column(default=None)
    acknowledged_by_operator_id: Mapped[str | None] = mapped_column(default=None)
    source_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("session_events.id", ondelete="SET NULL"), default=None
    )


class OperatorObservation(Base):
    """Явно зафиксированная оператором проверка состояния участка."""

    __tablename__ = "operator_observations"
    __table_args__ = (Index("ix_operator_observations_session_sim_time", "session_id", "sim_time_ms"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    request_id: Mapped[UuidStr] = mapped_column(unique=True)
    session_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    sequence_no: Mapped[int]
    sim_time_ms: Mapped[int]
    observation_type: Mapped[Code] = mapped_column(index=True)
    target_code: Mapped[Code]
    payload_json: Mapped[JsonDict]
    received_at: Mapped[Timestamp]


class OperatorDiagnosis(Base):
    """Предполагаемая оператором первопричина отклонения."""

    __tablename__ = "operator_diagnoses"
    __table_args__ = (Index("ix_operator_diagnoses_session_sim_time", "session_id", "sim_time_ms"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    request_id: Mapped[UuidStr] = mapped_column(unique=True)
    session_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    sequence_no: Mapped[int]
    sim_time_ms: Mapped[int]
    affected_area_code: Mapped[Code]
    deviation_code: Mapped[Code]
    suspected_cause_code: Mapped[Code]
    confidence: Mapped[float | None] = mapped_column(default=None)
    # Внутреннее поле отчёта: во время прохождения оператору не возвращается.
    is_correct: Mapped[bool]
    received_at: Mapped[Timestamp]
