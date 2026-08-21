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
from app.infrastructure.db.models.identity import (
    AuthSession,
    SecurityEvent,
    User,
    UserRoleAssignment,
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
    NasaTlxResponse,
    OperatorAction,
    OperatorDiagnosis,
    OperatorObservation,
    ProcessSnapshot,
    SagatAnswer,
    SagatCheckpoint,
    ScoreEventRecord,
    SessionAlarm,
    SessionEvent,
    SessionReport,
    SessionScore,
    SessionStageHistory,
    TrainingSession,
)

__all__ = [
    "SCHEMA_VERSION",
    "AlarmRule",
    "AuthSession",
    "Base",
    "CommandRequest",
    "DisturbanceTemplate",
    "Equipment",
    "ExpectedActionRule",
    "InstallationVersion",
    "NasaTlxResponse",
    "OperatorAction",
    "OperatorDiagnosis",
    "OperatorObservation",
    "ProcessSnapshot",
    "ProcessTag",
    "SagatAnswer",
    "SagatCheckpoint",
    "ScenarioLevel",
    "ScenarioStage",
    "ScenarioVersion",
    "ScoreEventRecord",
    "ScoringPolicyVersion",
    "SecurityEvent",
    "SessionAlarm",
    "SessionEvent",
    "SessionReport",
    "SessionScore",
    "SessionStageHistory",
    "TopologyEdge",
    "TrainingSession",
    "User",
    "UserRoleAssignment",
]
