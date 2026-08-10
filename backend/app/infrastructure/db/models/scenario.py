from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base
from app.infrastructure.db.models.catalog import InstallationVersion
from app.infrastructure.db.types import (
    Code,
    JsonDict,
    JsonList,
    Name,
    Timestamp,
    UtcDateTime,
    UuidStr,
    new_uuid,
)


class ScenarioVersion(Base):
    """Версия сквозного сценария. После публикации не редактируется."""

    __tablename__ = "scenario_versions"
    __table_args__ = (UniqueConstraint("scenario_code", "version"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    scenario_code: Mapped[Code]
    version: Mapped[int]
    installation_version_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("installation_versions.id"), index=True
    )
    name: Mapped[Name]
    description: Mapped[str] = mapped_column(default="")
    duration_ms: Mapped[int]
    status: Mapped[Code]
    config_json: Mapped[JsonDict]
    created_at: Mapped[Timestamp]
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    installation_version: Mapped[InstallationVersion] = relationship()
    levels: Mapped[list["ScenarioLevel"]] = relationship(
        back_populates="scenario_version", cascade="all, delete-orphan"
    )
    stages: Mapped[list["ScenarioStage"]] = relationship(
        back_populates="scenario_version", cascade="all, delete-orphan", order_by="ScenarioStage.order_no"
    )
    alarm_rules: Mapped[list["AlarmRule"]] = relationship(
        back_populates="scenario_version", cascade="all, delete-orphan"
    )
    disturbance_templates: Mapped[list["DisturbanceTemplate"]] = relationship(
        back_populates="scenario_version", cascade="all, delete-orphan"
    )
    expected_action_rules: Mapped[list["ExpectedActionRule"]] = relationship(
        back_populates="scenario_version", cascade="all, delete-orphan"
    )


class ScenarioLevel(Base):
    """Уровень сложности: одна логика сценария с другими скоростями, помехами и дедлайном."""

    __tablename__ = "scenario_levels"
    __table_args__ = (UniqueConstraint("scenario_version_id", "level_no"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    scenario_version_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("scenario_versions.id", ondelete="CASCADE"), index=True
    )
    level_no: Mapped[int]
    sensor_delay_ms: Mapped[int]
    nuisance_alarm_rate: Mapped[float]
    reaction_deadline_ms: Mapped[int]
    development_speed_factor: Mapped[float]
    hints_enabled: Mapped[bool]
    reserve_config_json: Mapped[JsonDict]

    scenario_version: Mapped[ScenarioVersion] = relationship(back_populates="levels")


class ScenarioStage(Base):
    """Этап сценария с условиями входа, успеха, провала и обязательными проверками."""

    __tablename__ = "scenario_stages"
    __table_args__ = (
        UniqueConstraint("scenario_version_id", "code"),
        UniqueConstraint("scenario_version_id", "order_no"),
    )

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    scenario_version_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("scenario_versions.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[Code]
    order_no: Mapped[int]
    entry_rule_json: Mapped[JsonDict]
    success_rule_json: Mapped[JsonDict]
    failure_rule_json: Mapped[JsonDict]
    timeout_ms: Mapped[int]
    required_checks_json: Mapped[JsonList]

    scenario_version: Mapped[ScenarioVersion] = relationship(back_populates="stages")


class AlarmRule(Base):
    """Правило тревоги: порог включения, гистерезис, задержка и уровень L1…L5."""

    __tablename__ = "alarm_rules"
    __table_args__ = (UniqueConstraint("scenario_version_id", "code"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    scenario_version_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("scenario_versions.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[Code]
    level: Mapped[Code]
    equipment_code: Mapped[Code]
    source_expression_json: Mapped[JsonDict]
    activation_delay_ms: Mapped[int]
    clear_expression_json: Mapped[JsonDict]
    ack_required: Mapped[bool]
    message_template: Mapped[Name]

    scenario_version: Mapped[ScenarioVersion] = relationship(back_populates="alarm_rules")


class DisturbanceTemplate(Base):
    """Шаблон скрытого возмущения. `hidden_config_json` не покидает backend."""

    __tablename__ = "disturbance_templates"
    __table_args__ = (UniqueConstraint("scenario_version_id", "code"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    scenario_version_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("scenario_versions.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[Code]
    cause_code: Mapped[Code]
    eligible_targets_json: Mapped[JsonList]
    onset_rule_json: Mapped[JsonDict]
    development_rule_json: Mapped[JsonDict]
    recovery_rule_json: Mapped[JsonDict]
    hidden_config_json: Mapped[JsonDict]

    scenario_version: Mapped[ScenarioVersion] = relationship(back_populates="disturbance_templates")


class ExpectedActionRule(Base):
    """Эталонный шаг оператора: предусловия, окно, ожидаемый эффект и вес в оценке."""

    __tablename__ = "expected_action_rules"
    __table_args__ = (UniqueConstraint("scenario_version_id", "situation_code", "action_type"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    scenario_version_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("scenario_versions.id", ondelete="CASCADE"), index=True
    )
    situation_code: Mapped[Code]
    action_type: Mapped[Code]
    target_selector: Mapped[Code]
    order_no: Mapped[int]
    required_preconditions_json: Mapped[JsonList]
    valid_window_ms: Mapped[int]
    expected_effect_json: Mapped[JsonDict]
    verification_rule_json: Mapped[JsonDict]
    criticality: Mapped[Code]
    weight: Mapped[float]

    scenario_version: Mapped[ScenarioVersion] = relationship(back_populates="expected_action_rules")


class ScoringPolicyVersion(Base):
    """Версия политики оценки: веса и штрафы не зашиваются в код."""

    __tablename__ = "scoring_policy_versions"
    __table_args__ = (UniqueConstraint("code", "version"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    code: Mapped[Code]
    version: Mapped[int]
    status: Mapped[Code]
    weights_json: Mapped[JsonDict]
    penalties_json: Mapped[JsonDict]
    stability_rule_json: Mapped[JsonDict]
    reaction_rule_json: Mapped[JsonDict]
    created_at: Mapped[Timestamp]
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
