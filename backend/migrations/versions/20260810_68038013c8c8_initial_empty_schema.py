"""initial empty schema

Revision ID: 68038013c8c8
Revises:
Create Date: 2026-08-10 18:28:04.436528

"""

revision: str = "68038013c8c8"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Базовая точка истории миграций; таблицы добавляются следующими ревизиями."""


def downgrade() -> None:
    pass
