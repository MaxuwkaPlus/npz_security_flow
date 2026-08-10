from dataclasses import dataclass, field


@dataclass(frozen=True)
class TagSpec:
    """Технологический параметр. Код тега совпадает с именем поля в snapshot."""

    code: str
    unit: str
    value_type: str = "float"
    normal_min: float | None = None
    normal_max: float | None = None
    warning_min: float | None = None
    warning_max: float | None = None
    critical_min: float | None = None
    critical_max: float | None = None
    visible_to_operator: bool = True


@dataclass(frozen=True)
class EquipmentSpec:
    code: str
    equipment_type: str
    display_name: str
    parent_code: str | None = None
    tags: tuple[TagSpec, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class EdgeSpec:
    from_code: str
    to_code: str
    stream_code: str
    stream_type: str
    branch_no: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class InstallationSpec:
    code: str
    version: int
    name: str
    config: dict[str, object]
    equipment: tuple[EquipmentSpec, ...]
    edges: tuple[EdgeSpec, ...]
