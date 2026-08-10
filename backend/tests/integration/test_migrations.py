from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.infrastructure.db.models import Base

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_upgrade_head_creates_full_schema_on_clean_database(tmp_path: Path) -> None:
    db_file = tmp_path / "migrations.db"
    config = alembic_config(f"sqlite+aiosqlite:///{db_file}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert "alembic_version" in tables
    assert set(Base.metadata.tables) <= tables


def test_downgrade_to_base_is_supported(tmp_path: Path) -> None:
    db_file = tmp_path / "migrations.db"
    config = alembic_config(f"sqlite+aiosqlite:///{db_file}")
    command.upgrade(config, "head")

    command.downgrade(config, "base")

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert set(Base.metadata.tables) & tables == set()
