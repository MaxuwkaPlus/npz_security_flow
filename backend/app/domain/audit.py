"""Словарь журнала событий безопасности.

Коды событий — часть контракта с администратором ИБ: по ним строятся выборки при
расследовании, поэтому значения стабильны и меняются только с миграцией данных.
"""

from enum import StrEnum


class SecurityEventType(StrEnum):
    LOGIN = "login"
    LOGOUT = "logout"
    # Вход без учётной записи. Отдельный код, а не LOGIN: администратору ИБ нужно
    # отличать проверенный вход от самостоятельного прохождения без проверки личности.
    GUEST_SESSION = "guest_session"
    ACCESS_DENIED = "access_denied"
    USER_CREATED = "user_created"
    USER_DEACTIVATED = "user_deactivated"
    ROLE_GRANTED = "role_granted"
    ROLE_REVOKED = "role_revoked"
    PASSWORD_CHANGED = "password_changed"


class Outcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
