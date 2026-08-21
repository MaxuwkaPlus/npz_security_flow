"""Ролевая модель доступа с минимальными правами (§4 технического задания).

Модуль отвечает на один вопрос: какому субъекту какое действие разрешено. Он не знает
ни про HTTP, ни про базу, поэтому его правила проверяются модульными тестами без поднятия
приложения.

Права намеренно мельче ролей. Роль — это удобная упаковка, а решение всегда принимается
по конкретному праву: набор ролей меняется от заказчика к заказчику, а разделение
полномочий должно сохраняться. Отсюда же инвариант из требования: автор сценариев не
получает права менять системные правила безопасности и удалять результаты обучения.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class Permission(StrEnum):
    """Атомарное разрешение. Значение — стабильный машинный код для журнала аудита."""

    # Каталог и содержание обучения.
    CATALOG_READ = "catalog.read"
    SCENARIO_EDIT = "scenario.edit"

    # Прохождение. Назначение сценария, управление ходом и работа за пультом — три
    # разных права: инструктор ведёт сессию, но не выполняет её за оператора.
    SESSION_CREATE = "session.create"
    SESSION_CONTROL = "session.control"
    # Самостоятельное прохождение: вести ход можно, но только своей сессии. Отдельное
    # право, а не ослабленный SESSION_CONTROL, — иначе «ведёт чужое обучение» и «сам
    # себе включил тренажёр» стали бы неразличимы в матрице и в журнале.
    SESSION_CONTROL_OWN = "session.control_own"
    SESSION_OPERATE = "session.operate"
    SESSION_READ_OWN = "session.read_own"
    SESSION_READ_ANY = "session.read_any"

    # Результаты обучения.
    REPORT_READ_OWN = "report.read_own"
    REPORT_READ_ANY = "report.read_any"
    RESULTS_DELETE = "results.delete"
    DATA_EXPORT = "data.export"

    # Системные правила и модели. Отделены от редактирования сценария сознательно.
    SAFETY_RULES_EDIT = "safety_rules.edit"
    SCORING_EDIT = "scoring.edit"
    RISK_MODEL_EDIT = "risk_model.edit"
    PROPOSAL_REVIEW = "proposal.review"

    # Информационная безопасность.
    AUDIT_READ = "audit.read"
    SECURITY_POLICY_MANAGE = "security_policy.manage"
    ACCOUNT_MANAGE = "account.manage"


class Role(StrEnum):
    """Роль субъекта. MVP реализует первые четыре, остальные объявлены заранее."""

    # Самостоятельный обучаемый: вошёл без учётной записи и работает только со своим
    # прохождением. Роль выдаётся сервером при выдаче гостевого токена и недоступна
    # администратору для назначения — см. MVP_ROLES.
    GUEST = "guest"

    TRAINEE = "trainee"
    INSTRUCTOR = "instructor"
    EXPERT = "expert"
    SECURITY_ADMIN = "security_admin"

    SCENARIO_AUTHOR = "scenario_author"
    ADMIN = "admin"
    SUPPORT = "support"


# Роли текущего этапа. Остальные описаны в матрице, но пока не назначаются: модель
# полная и проверяемая тестами, а поверхность доступа — только та, что реализована.
#
# GUEST сюда не входит намеренно: гостевую роль выдаёт себе сервер вместе с гостевым
# токеном, и назначить её учётной записи администратор не может. Иначе постоянный
# пользователь получил бы право вести ход прохождения в обход инструктора.
MVP_ROLES: frozenset[Role] = frozenset({Role.TRAINEE, Role.INSTRUCTOR, Role.EXPERT, Role.SECURITY_ADMIN})


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    # Гость проходит тренажёр без учётной записи: заводит прохождение себе, сам его
    # запускает и работает за пультом. Границы те же, что у обучаемого, — чужого он
    # не видит, — но ход ведёт сам, потому что инструктора у него нет.
    Role.GUEST: frozenset(
        {
            Permission.CATALOG_READ,
            Permission.SESSION_CREATE,
            Permission.SESSION_CONTROL_OWN,
            Permission.SESSION_OPERATE,
            Permission.SESSION_READ_OWN,
            Permission.REPORT_READ_OWN,
        }
    ),
    # Обучаемый видит только назначенное ему и только свои результаты.
    Role.TRAINEE: frozenset(
        {
            Permission.CATALOG_READ,
            Permission.SESSION_OPERATE,
            Permission.SESSION_READ_OWN,
            Permission.REPORT_READ_OWN,
        }
    ),
    # Инструктор назначает и ведёт прохождение, но не правит конфигурацию тренажёра.
    Role.INSTRUCTOR: frozenset(
        {
            Permission.CATALOG_READ,
            Permission.SESSION_CREATE,
            Permission.SESSION_CONTROL,
            Permission.SESSION_READ_ANY,
            Permission.REPORT_READ_ANY,
        }
    ),
    # Эксперт разбирает результаты и утверждает предложения, но не меняет ни сценарий,
    # ни модель напрямую: рекомендация входит в тренажёр только через утверждение.
    Role.EXPERT: frozenset(
        {
            Permission.CATALOG_READ,
            Permission.SESSION_READ_ANY,
            Permission.REPORT_READ_ANY,
            Permission.DATA_EXPORT,
            Permission.PROPOSAL_REVIEW,
        }
    ),
    # Администратор ИБ работает с журналом и доступом. Содержание отчётов об обучении
    # для расследования не нужно, поэтому REPORT_READ_ANY ему не выдаётся.
    Role.SECURITY_ADMIN: frozenset(
        {
            Permission.AUDIT_READ,
            Permission.SECURITY_POLICY_MANAGE,
            Permission.ACCOUNT_MANAGE,
            Permission.SESSION_READ_ANY,
        }
    ),
    # Дальнейшая реализация.
    #
    # Автор сценариев ограничен своей рабочей областью: правила безопасности, scoring,
    # модель риска и удаление результатов лежат вне его полномочий.
    Role.SCENARIO_AUTHOR: frozenset(
        {
            Permission.CATALOG_READ,
            Permission.SCENARIO_EDIT,
        }
    ),
    # Администратор ведёт конфигурацию и учётные записи, но не читает результаты обучения.
    Role.ADMIN: frozenset(
        {
            Permission.CATALOG_READ,
            Permission.SCENARIO_EDIT,
            Permission.SAFETY_RULES_EDIT,
            Permission.SCORING_EDIT,
            Permission.RISK_MODEL_EDIT,
            Permission.RESULTS_DELETE,
            Permission.ACCOUNT_MANAGE,
        }
    ),
    # Техподдержка видит факт и состояние прохождения, но не его содержание.
    Role.SUPPORT: frozenset(
        {
            Permission.CATALOG_READ,
            Permission.SESSION_READ_ANY,
        }
    ),
}


# Права, которые требование выделяет как критичные для разделения полномочий.
# Список существует, чтобы изменение матрицы нельзя было внести незаметно: тест
# сверяет с ним фактические наборы ролей.
SEPARATED_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.SESSION_CONTROL,
        Permission.SCENARIO_EDIT,
        Permission.SAFETY_RULES_EDIT,
        Permission.SCORING_EDIT,
        Permission.RISK_MODEL_EDIT,
        Permission.RESULTS_DELETE,
        Permission.DATA_EXPORT,
        Permission.ACCOUNT_MANAGE,
    }
)


@dataclass(frozen=True)
class Principal:
    """Субъект запроса: кто пришёл и с какими ролями.

    `subject_id` совпадает с `operator_id` сессии, поэтому проверка «свой ресурс»
    выполняется сравнением идентификаторов, а не отдельным справочником.
    """

    user_id: str
    subject_id: str
    roles: frozenset[Role]

    @property
    def permissions(self) -> frozenset[Permission]:
        return permissions_for(self.roles)

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions

    def has_any(self, *permissions: Permission) -> bool:
        return any(self.has(permission) for permission in permissions)


def permissions_for(roles: Iterable[Role]) -> frozenset[Permission]:
    """Объединение прав всех ролей субъекта."""

    granted: set[Permission] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS[role]
    return frozenset(granted)


def is_assignable(role: Role) -> bool:
    """Можно ли выдать роль на текущем этапе."""

    return role in MVP_ROLES


def can_read_session(principal: Principal, operator_id: str) -> bool:
    """Доступ к прохождению: чужое — только по праву на любую сессию."""

    if principal.has(Permission.SESSION_READ_ANY):
        return True
    return principal.has(Permission.SESSION_READ_OWN) and principal.subject_id == operator_id


def can_read_report(principal: Principal, operator_id: str) -> bool:
    """Доступ к отчёту: своё — обучаемому, чужое — по праву на любой отчёт."""

    if principal.has(Permission.REPORT_READ_ANY):
        return True
    return principal.has(Permission.REPORT_READ_OWN) and principal.subject_id == operator_id


def can_control_session(principal: Principal, operator_id: str) -> bool:
    """Кто ведёт ход прохождения: пуск, пауза, продолжение, досрочное прекращение.

    Инструктор ведёт любое назначенное им обучение. Гость, у которого инструктора нет,
    управляет только собственным прохождением: без этого самостоятельный запуск
    тренажёра потребовал бы выдать ему власть над чужими сессиями.
    """

    if principal.has(Permission.SESSION_CONTROL):
        return True
    return principal.has(Permission.SESSION_CONTROL_OWN) and principal.subject_id == operator_id


def can_assign_session(principal: Principal, operator_id: str) -> bool:
    """Кому можно завести прохождение: инструктору — любому, остальным — только себе.

    Право заводить сессию само по себе не даёт назначать её чужим именем: иначе гость
    подписал бы своё прохождение чужим идентификатором и исказил чужие результаты.
    """

    if not principal.has(Permission.SESSION_CREATE):
        return False
    if principal.has(Permission.SESSION_CONTROL):
        return True
    return principal.subject_id == operator_id


def can_operate_session(principal: Principal, operator_id: str) -> bool:
    """За пультом работает только тот обучаемый, которому сессия назначена.

    Инструктор ведёт прохождение, но не выполняет команды вместо оператора: иначе
    журнал перестал бы отвечать на вопрос, чей это навык.
    """

    return principal.has(Permission.SESSION_OPERATE) and principal.subject_id == operator_id
