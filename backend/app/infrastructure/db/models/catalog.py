from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base
from app.infrastructure.db.types import Code, JsonDict, Name, Timestamp, UtcDateTime, UuidStr, new_uuid


class InstallationVersion(Base):
    """Неизменяемая после публикации версия установки и её каталога."""

    __tablename__ = "installation_versions"
    __table_args__ = (UniqueConstraint("installation_code", "version"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    installation_code: Mapped[Code]
    version: Mapped[int]
    name: Mapped[Name]
    status: Mapped[Code]
    config_json: Mapped[JsonDict]
    created_at: Mapped[Timestamp]
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    equipment: Mapped[list["Equipment"]] = relationship(
        back_populates="installation_version", cascade="all, delete-orphan"
    )
    topology_edges: Mapped[list["TopologyEdge"]] = relationship(
        back_populates="installation_version", cascade="all, delete-orphan"
    )


class Equipment(Base):
    """Аппарат установки: Т-4/1, Э-3, К-1 и т. д."""

    __tablename__ = "equipment"
    __table_args__ = (UniqueConstraint("installation_version_id", "code"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    installation_version_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("installation_versions.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[Code]
    equipment_type: Mapped[Code]
    parent_equipment_id: Mapped[str | None] = mapped_column(
        ForeignKey("equipment.id", ondelete="SET NULL"), default=None, index=True
    )
    display_name: Mapped[Name]
    metadata_json: Mapped[JsonDict]

    installation_version: Mapped[InstallationVersion] = relationship(back_populates="equipment")
    tags: Mapped[list["ProcessTag"]] = relationship(back_populates="equipment", cascade="all, delete-orphan")


class ProcessTag(Base):
    """Технологический параметр аппарата с границами нормы, предупреждения и критики."""

    __tablename__ = "process_tags"
    __table_args__ = (UniqueConstraint("equipment_id", "code"),)

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    equipment_id: Mapped[UuidStr] = mapped_column(ForeignKey("equipment.id", ondelete="CASCADE"), index=True)
    code: Mapped[Code] = mapped_column(index=True)
    value_type: Mapped[Code]
    unit: Mapped[Code]
    normal_min: Mapped[float | None] = mapped_column(default=None)
    normal_max: Mapped[float | None] = mapped_column(default=None)
    warning_min: Mapped[float | None] = mapped_column(default=None)
    warning_max: Mapped[float | None] = mapped_column(default=None)
    critical_min: Mapped[float | None] = mapped_column(default=None)
    critical_max: Mapped[float | None] = mapped_column(default=None)
    visible_to_operator: Mapped[bool] = mapped_column(default=True)
    metadata_json: Mapped[JsonDict]

    equipment: Mapped[Equipment] = relationship(back_populates="tags")


class TopologyEdge(Base):
    """Направленная связь между аппаратами: по ней распространяется возмущение."""

    __tablename__ = "topology_edges"

    id: Mapped[UuidStr] = mapped_column(primary_key=True, default=new_uuid)
    installation_version_id: Mapped[UuidStr] = mapped_column(
        ForeignKey("installation_versions.id", ondelete="CASCADE"), index=True
    )
    from_equipment_id: Mapped[UuidStr] = mapped_column(ForeignKey("equipment.id", ondelete="CASCADE"))
    to_equipment_id: Mapped[UuidStr] = mapped_column(ForeignKey("equipment.id", ondelete="CASCADE"))
    stream_code: Mapped[Code]
    branch_no: Mapped[int | None] = mapped_column(default=None)
    stream_type: Mapped[Code]
    metadata_json: Mapped[JsonDict]

    installation_version: Mapped[InstallationVersion] = relationship(back_populates="topology_edges")
