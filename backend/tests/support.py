from pathlib import Path
from typing import Any

from alembic.config import Config

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


# Постоянные времени модели, сокращённые для тестов. Формулы те же — иначе один прогон
# цепочки занимал бы час симуляционного времени и десятки тысяч тиков.
FAST_PROCESS_MODEL: dict[str, Any] = {
    "warmup_time_constant_ms": 30_000,
    "flow_time_constant_ms": 20_000,
    "downstream": {
        "elou_load_time_constant_ms": 20_000,
        "elou_stage2_time_constant_ms": 10_000,
        "elou_level_time_constant_ms": 10_000,
        "e15_load_time_constant_ms": 10_000,
        "e15_level_time_constant_ms": 10_000,
        "k1_load_time_constant_ms": 10_000,
        "k1_time_constant_ms": 20_000,
        "furnace_time_constant_ms": 20_000,
        "k2_load_time_constant_ms": 30_000,
        "k2_time_constant_ms": 30_000,
        "product_time_constant_ms": 30_000,
    },
}


def speed_up_process_model(config: dict[str, Any]) -> dict[str, Any]:
    """Копия конфигурации сценария с ускоренной динамикой участков."""

    updated = dict(config)
    model = dict(updated["process_model"])
    model.update({key: value for key, value in FAST_PROCESS_MODEL.items() if key != "downstream"})
    model["downstream"] = model["downstream"] | FAST_PROCESS_MODEL["downstream"]
    updated["process_model"] = model
    return updated
