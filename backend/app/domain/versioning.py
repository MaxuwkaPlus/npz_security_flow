from enum import StrEnum


class PublicationStatus(StrEnum):
    """Опубликованная версия конфигурации неизменяема и не редактируется задним числом."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"
