"""Служебные команды backend: `uv run python -m app.cli seed`."""

import argparse
import asyncio
import secrets

from app.application.accounts import create_user
from app.application.configuration import publish_installation, publish_scenario, publish_scoring_policy
from app.domain.rbac import ROLE_PERMISSIONS, Permission, Principal, Role, is_assignable
from app.infrastructure.db.engine import Database
from app.infrastructure.db.unit_of_work import UnitOfWork
from app.infrastructure.seed.accounts import DEMO_ACCOUNTS
from app.infrastructure.seed.installation import build_installation_spec
from app.settings import Settings

# Субъект начальной загрузки: учётных записей ещё нет, а событие в журнале
# безопасности должно быть подписано.
BOOTSTRAP = Principal(
    user_id="bootstrap",
    subject_id="bootstrap",
    roles=frozenset({Role.SECURITY_ADMIN}),
)

GENERATED_PASSWORD_BYTES = 12


async def seed() -> None:
    """Публикует демонстрационную конфигурацию. Команда идемпотентна."""

    database = Database(Settings())
    try:
        async with database.session_factory() as session, session.begin():
            installation = await publish_installation(session, build_installation_spec())
            scenario = await publish_scenario(session, installation)
            policy = await publish_scoring_policy(session)
            print(f"installation {installation.installation_code} v{installation.version}: {installation.id}")
            print(f"scenario     {scenario.scenario_code} v{scenario.version}: {scenario.id}")
            print(f"scoring      {policy.code} v{policy.version}: {policy.id}")
    finally:
        await database.dispose()


async def seed_users() -> None:
    """Заводит по учётной записи на каждую роль MVP со случайным паролем.

    Пароль печатается один раз и нигде не сохраняется: держать его в коде или в
    примере конфигурации нельзя. Уже существующие записи пропускаются, поэтому
    повторный запуск не сбрасывает пароли.
    """

    database = Database(Settings())
    created: list[tuple[str, str]] = []
    try:
        async with UnitOfWork(database.session_factory) as uow:
            for spec in DEMO_ACCOUNTS:
                if await uow.identity.get_user_by_username(spec.username) is not None:
                    print(f"{spec.username:<14} уже заведён, пропущен")
                    continue
                password = secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)
                await create_user(
                    uow,
                    BOOTSTRAP,
                    username=spec.username,
                    display_name=spec.display_name,
                    password=password,
                    roles=spec.roles,
                )
                created.append((spec.username, password))
    finally:
        await database.dispose()

    if not created:
        return
    print("\nПароли показаны один раз, сохраните их сейчас:")
    for username, password in created:
        print(f"  {username:<14} {password}")


def show_matrix() -> None:
    """Печатает матрицу ролей и прав — то же, что отдаёт GET /api/v1/roles."""

    width = max(len(permission.value) for permission in Permission) + 2
    header = "".join(f"{role.value[:12]:<14}" for role in Role)
    print(f"{'право':<{width}}{header}")
    for permission in Permission:
        marks = "".join(f"{('да' if permission in ROLE_PERMISSIONS[role] else '·'):<14}" for role in Role)
        print(f"{permission.value:<{width}}{marks}")
    postponed = sorted(role.value for role in Role if not is_assignable(role))
    print(f"\nследующий цикл (пока не назначаются): {', '.join(postponed)}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    parser.add_argument("command", choices=["seed", "seed-users", "roles"])
    arguments = parser.parse_args()

    if arguments.command == "seed":
        asyncio.run(seed())
    elif arguments.command == "seed-users":
        asyncio.run(seed_users())
    else:
        show_matrix()


if __name__ == "__main__":
    main()
