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

__all__ = [
    "AlarmRule",
    "Base",
    "DisturbanceTemplate",
    "Equipment",
    "ExpectedActionRule",
    "InstallationVersion",
    "ProcessTag",
    "ScenarioLevel",
    "ScenarioStage",
    "ScenarioVersion",
    "ScoringPolicyVersion",
    "TopologyEdge",
]
