"""Токены сеанса.

Токен непрозрачный и случайный: в нём нет ролей и срока, поэтому подделать его нельзя,
а отзыв действует сразу — состояние хранится на сервере. В базу кладётся только SHA-256
от токена, чтобы утечка дампа не давала доступа.
"""

import hashlib
import secrets

TOKEN_BYTES = 32


def issue_token() -> tuple[str, str]:
    """Возвращает пару «токен клиенту, хеш для хранения»."""

    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
