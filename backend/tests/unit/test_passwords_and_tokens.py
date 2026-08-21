"""Хеширование паролей и выдача токенов."""

import pytest

from app.infrastructure.security.passwords import (
    MIN_PASSWORD_LENGTH,
    WeakPasswordError,
    hash_password,
    validate_password_policy,
    verify_password,
)
from app.infrastructure.security.tokens import hash_token, issue_token


def test_same_password_gives_different_hashes() -> None:
    """У каждого пароля своя соль, иначе одинаковые пароли видны по дампу."""

    first = hash_password("одинаковый пароль")
    second = hash_password("одинаковый пароль")

    assert first != second
    assert verify_password("одинаковый пароль", first)
    assert verify_password("одинаковый пароль", second)


def test_wrong_password_is_rejected() -> None:
    encoded = hash_password("правильный пароль")

    assert not verify_password("другой пароль", encoded)


def test_hash_does_not_contain_the_password() -> None:
    assert "секретный пароль" not in hash_password("секретный пароль")


@pytest.mark.parametrize("encoded", ["", "мусор", "scrypt$1$2", "bcrypt$1$8$1$c2FsdA==$a2V5"])
def test_broken_record_is_not_a_match(encoded: str) -> None:
    """Повреждённая или чужая запись не должна проходить проверку и не должна падать."""

    assert not verify_password("любой пароль", encoded)


def test_password_policy_checks_length() -> None:
    validate_password_policy("x" * MIN_PASSWORD_LENGTH)

    with pytest.raises(WeakPasswordError):
        validate_password_policy("x" * (MIN_PASSWORD_LENGTH - 1))


def test_issued_token_is_stored_only_as_a_hash() -> None:
    token, stored = issue_token()

    assert token != stored
    assert stored == hash_token(token)
    assert token not in stored


def test_tokens_do_not_repeat() -> None:
    assert len({issue_token()[0] for _ in range(50)}) == 50
