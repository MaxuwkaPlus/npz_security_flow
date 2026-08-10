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

__all__ = ["Base", "Equipment", "InstallationVersion", "ProcessTag", "TopologyEdge"]
