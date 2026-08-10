"""Служебные команды backend: `uv run python -m app.cli seed`."""

import argparse
import asyncio

from app.application.configuration import publish_installation, publish_scenario, publish_scoring_policy
from app.infrastructure.db.engine import Database
from app.infrastructure.seed.installation import build_installation_spec
from app.settings import Settings


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    parser.add_argument("command", choices=["seed"])
    parser.parse_args()
    asyncio.run(seed())


if __name__ == "__main__":
    main()
