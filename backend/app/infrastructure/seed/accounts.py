"""Демонстрационные учётные записи по одной на каждую роль MVP.

Паролей здесь нет и быть не может: они генерируются при заведении и показываются
один раз. Логин совпадает с идентификатором оператора в журнале прохождений.
"""

from dataclasses import dataclass

from app.domain.rbac import Role


@dataclass(frozen=True)
class AccountSpec:
    username: str
    display_name: str
    roles: tuple[Role, ...]


DEMO_ACCOUNTS: tuple[AccountSpec, ...] = (
    AccountSpec("operator-1", "Оператор Иванов", (Role.TRAINEE,)),
    AccountSpec("operator-2", "Оператор Петров", (Role.TRAINEE,)),
    AccountSpec("instructor-1", "Инструктор Сидоров", (Role.INSTRUCTOR,)),
    AccountSpec("expert-1", "Эксперт Кузнецов", (Role.EXPERT,)),
    AccountSpec("iso-1", "Администратор ИБ Смирнов", (Role.SECURITY_ADMIN,)),
)
