"""ORM-модели. Импорт пакета регистрирует все таблицы в `Base.metadata`.

Alembic и интеграционные тесты берут схему только отсюда, поэтому каждая новая
модель обязана быть импортирована в этом модуле.
"""

from app.infrastructure.db.base import Base
from app.infrastructure.db.models.catalog import (
    Equipment,
    InstallationVersion,
    ProcessTag,
    TopologyEdge,
)
from app.infrastructure.db.models.scenario import (
    AlarmRule,
    DisturbanceTemplate,
    ExpectedActionRule,
    ScenarioLevel,
    ScenarioStage,
    ScenarioVersion,
    ScoringPolicyVersion,
)
from app.infrastructure.db.models.session import (
    SCHEMA_VERSION,
    CommandRequest,
    OperatorAction,
    ProcessSnapshot,
    SessionAlarm,
    SessionEvent,
    SessionStageHistory,
    TrainingSession,
)

__all__ = [
    "SCHEMA_VERSION",
    "AlarmRule",
    "Base",
    "CommandRequest",
    "DisturbanceTemplate",
    "Equipment",
    "ExpectedActionRule",
    "InstallationVersion",
    "OperatorAction",
    "ProcessSnapshot",
    "ProcessTag",
    "ScenarioLevel",
    "ScenarioStage",
    "ScenarioVersion",
    "ScoringPolicyVersion",
    "SessionAlarm",
    "SessionEvent",
    "SessionStageHistory",
    "TopologyEdge",
    "TrainingSession",
]
