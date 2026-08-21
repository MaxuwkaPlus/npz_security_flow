"""Хранение паролей.

Стандартной библиотеки достаточно: `hashlib.scrypt` — это KDF с настраиваемой ценой,
поэтому внешняя зависимость ради хеширования пароля не нужна. Соль у каждого пароля своя,
сравнение — постоянного времени.
"""

import hashlib
import hmac
import secrets
from base64 import b64decode, b64encode

ALGORITHM = "scrypt"
# Параметры цены: ~64 МБ памяти на проверку. Подбор пароля дорожает, а вход одного
# пользователя остаётся в пределах десятков миллисекунд.
COST = 2**16
BLOCK_SIZE = 8
PARALLELISM = 1
SALT_BYTES = 16
KEY_BYTES = 32

MIN_PASSWORD_LENGTH = 12


class WeakPasswordError(ValueError):
    """Пароль не удовлетворяет политике."""


def hash_password(password: str) -> str:
    """Возвращает самодостаточную строку: алгоритм, параметры, соль и ключ."""

    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive(password, salt)
    parts = (
        ALGORITHM,
        str(COST),
        str(BLOCK_SIZE),
        str(PARALLELISM),
        b64encode(salt).decode("ascii"),
        b64encode(key).decode("ascii"),
    )
    return "$".join(parts)


def verify_password(password: str, encoded: str) -> bool:
    """Проверяет пароль по сохранённой строке. Повреждённая запись — не совпадение."""

    try:
        algorithm, cost, block_size, parallelism, salt_b64, key_b64 = encoded.split("$")
        if algorithm != ALGORITHM:
            return False
        expected = b64decode(key_b64)
        actual = _derive(
            password,
            b64decode(salt_b64),
            cost=int(cost),
            block_size=int(block_size),
            parallelism=int(parallelism),
            key_length=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def validate_password_policy(password: str) -> None:
    """Минимальная политика: длина. Проверяется при заведении и смене пароля."""

    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(f"Пароль короче {MIN_PASSWORD_LENGTH} символов")


def _derive(
    password: str,
    salt: bytes,
    *,
    cost: int = COST,
    block_size: int = BLOCK_SIZE,
    parallelism: int = PARALLELISM,
    key_length: int = KEY_BYTES,
) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=cost,
        r=block_size,
        p=parallelism,
        dklen=key_length,
        maxmem=cost * block_size * 256,
    )
