"""Два демонстрационных прохождения сквозного сценария (§19 ТЗ).

Оба идут только через публичный API — так же, как их пройдёт фронтенд. Динамика модели
ускорена, чтобы прогон занимал секунды, а не 65 минут симуляционного времени.
"""

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.application.tick import run_tick
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import ScenarioVersion, TrainingSession
from app.infrastructure.db.unit_of_work import UnitOfWork
from tests.conftest import SeededConfiguration
from tests.support import speed_up_process_model

STARTUP_ACTIONS = (
    ("start_feed_pump", "N-1", {}),
    ("set_wash_water", "ELOU", {"ratio": 0.075}),
    ("start_transfer_pump", "N-20", {}),
)
PRECHECK_TARGETS = ("FEED-SYSTEM", "T-1_T-11", "ELOU", "K-2")
DOWNSTREAM_TARGETS = ("T-1_T-11", "ELOU", "V-15", "K-1", "FURNACES", "K-2", "PRODUCTS")


class Operator:
    """Тонкая обёртка над публичным API: тест читается как действия оператора."""

    def __init__(self, client: AsyncClient, database: Database, session_id: str) -> None:
        self._client = client
        self._database = database
        self.session_id = session_id

    async def act(self, action_type: str, target: str, **value: float) -> dict[str, Any]:
        response = await self._client.post(
            f"/api/v1/sessions/{self.session_id}/actions",
            json={
                "request_id": str(uuid4()),
                "action_type": action_type,
                "target_code": target,
                "value": value,
            },
        )
        assert response.status_code == 202, response.text
        return dict(response.json())

    async def observe(self, observation_type: str, target: str) -> None:
        response = await self._client.post(
            f"/api/v1/sessions/{self.session_id}/observations",
            json={
                "request_id": str(uuid4()),
                "observation_type": observation_type,
                "target_code": target,
            },
        )
        assert response.status_code == 201, response.text

    async def diagnose(self, cause_code: str) -> None:
        response = await self._client.post(
            f"/api/v1/sessions/{self.session_id}/diagnoses",
            json={
                "request_id": str(uuid4()),
                "affected_area_code": "FEED-SYSTEM",
                "deviation_code": "branch_flow_loss",
                "suspected_cause_code": cause_code,
            },
        )
        assert response.status_code == 201, response.text

    async def acknowledge_all_alarms(self) -> None:
        alarms = (await self._client.get(f"/api/v1/sessions/{self.session_id}/alarms")).json()
        for alarm in alarms:
            await self._client.post(
                f"/api/v1/sessions/{self.session_id}/alarms/{alarm['id']}/acknowledge",
                json={"request_id": str(uuid4())},
            )

    async def wait(self, seconds: int) -> None:
        for _ in range(seconds):
            async with UnitOfWork(self._database.session_factory) as uow:
                await run_tick(uow, self.session_id)

    async def state(self) -> dict[str, Any]:
        return dict((await self._client.get(f"/api/v1/sessions/{self.session_id}/state")).json())

    async def report(self) -> dict[str, Any]:
        response = await self._client.get(f"/api/v1/sessions/{self.session_id}/report")
        assert response.status_code == 200, response.text
        return dict(response.json())

    async def hidden_disturbance(self) -> dict[str, Any]:
        """Только для теста: он играет и за инструктора, который знает разгадку."""

        async with self._database.session_factory() as session:
            stored = await session.get(TrainingSession, self.session_id)
        assert stored is not None
        return dict(stored.hidden_runtime_config_json["disturbance"])


@pytest.fixture
async def operator(client: AsyncClient, database: Database, configuration: SeededConfiguration) -> Operator:
    async with database.session_factory() as session, session.begin():
        scenario = await session.get(ScenarioVersion, configuration.scenario_version_id)
        assert scenario is not None
        scenario.config_json = speed_up_process_model(scenario.config_json)

    created = await client.post(
        "/api/v1/sessions",
        json={
            "request_id": str(uuid4()),
            "operator_id": "demo-operator",
            "scenario_version_id": configuration.scenario_version_id,
            "level_no": 1,
            "random_seed": 42,
        },
    )
    assert created.status_code == 201, created.text
    session_id: str = created.json()["id"]
    await client.post(f"/api/v1/sessions/{session_id}/start", json={"request_id": str(uuid4())})
    return Operator(client, database, session_id)


async def bring_plant_online(operator: Operator) -> None:
    """Осмотр, пуск сырья, вода, откачка и розжиг печей — до устойчивого режима."""

    for target in PRECHECK_TARGETS:
        await operator.observe("inspect_equipment", target)
    for action_type, target, value in STARTUP_ACTIONS:
        await operator.act(action_type, target, **value)
    await operator.wait(200)
    await operator.act("set_furnace_heat_load", "FURNACES", heat_load_pct=100.0)
    await operator.wait(400)


async def corrective_target(operator: Operator) -> tuple[str, str]:
    hidden = await operator.hidden_disturbance()
    action_type = hidden["recovery"]["correct_action_type"]
    branch = hidden["target_branch"]
    target = "N-1A" if action_type == "switch_to_standby_pump" else f"FRC-40{3 + branch}"
    return action_type, target


async def test_wrong_diagnosis_and_dangerous_compensation_end_without_stabilization(
    operator: Operator,
) -> None:
    """Первое демонстрационное прохождение: оператор гасит симптом, а не причину."""

    await bring_plant_online(operator)
    await operator.wait(400)

    await operator.observe("declare_deviation", "FEED-SYSTEM")
    await operator.acknowledge_all_alarms()
    # Оператор решает, что дело в теплопередаче, и добавляет тепла печам.
    await operator.diagnose("heat_transfer_problem")
    await operator.act("set_furnace_heat_load", "FURNACES", heat_load_pct=125.0)
    await operator.wait(600)

    report = await operator.report()
    assert report["outcome"] == "not_stabilized"
    assert report["actions"]["by_classification"].get("dangerous") == 1
    assert report["downstream_checks"]["missing"]
    assert any("тепловой нагрузкой" in line for line in report["conclusions"])
    assert any("Первопричина не установлена" in line for line in report["conclusions"])
    assert report["scores"]["safety"] < 100.0


async def test_correct_diagnosis_and_downstream_checks_restore_the_plant(
    operator: Operator,
) -> None:
    """Второе демонстрационное прохождение: причина устранена, последствия проверены."""

    await bring_plant_online(operator)
    await operator.wait(400)

    await operator.observe("declare_deviation", "FEED-SYSTEM")
    await operator.acknowledge_all_alarms()
    await operator.observe("compare_flows", "FEED-SYSTEM")
    await operator.observe("inspect_pressure", "FEED-SYSTEM")
    await operator.observe("inspect_equipment", "N-1")

    hidden = await operator.hidden_disturbance()
    await operator.diagnose(hidden["cause_code"])
    action_type, target = await corrective_target(operator)
    await operator.act(action_type, target)
    await operator.wait(400)

    await operator.observe("verify_result", "FEED-SYSTEM")
    for downstream in DOWNSTREAM_TARGETS:
        await operator.observe("verify_result", downstream)
    await operator.acknowledge_all_alarms()
    await operator.wait(200)

    report = await operator.report()
    assert report["actions"]["by_classification"].get("correct") == 1
    assert report["actions"]["by_classification"].get("dangerous") is None
    assert report["downstream_checks"]["missing"] == []
    assert report["timings"]["reaction_time_ms"] is not None
    assert report["scores"]["action_correctness"] == 100.0
    assert any("Правильно определяет первопричину" in line for line in report["conclusions"])
    assert any("Прослеживает последствия" in line for line in report["conclusions"])

    state = await operator.state()
    assert state["current_stage_code"] in ("recovery", "final_stabilization")


async def test_two_runs_are_comparable_by_resultiveness(operator: Operator) -> None:
    """Оба прохождения дают сопоставимый набор баллов для сравнения уровней."""

    await bring_plant_online(operator)
    await operator.wait(400)
    await operator.observe("declare_deviation", "FEED-SYSTEM")
    hidden = await operator.hidden_disturbance()
    await operator.diagnose(hidden["cause_code"])
    action_type, target = await corrective_target(operator)
    await operator.act(action_type, target)
    await operator.wait(400)

    report = await operator.report()

    scores = report["scores"]
    assert set(scores) == {
        "safety",
        "action_correctness",
        "process_stability",
        "reaction_speed",
        "resultiveness",
        "situation_awareness",
        "raw_nasa_tlx",
    }
    assert all(
        0.0 <= value <= 100.0 for key, value in scores.items() if key != "raw_nasa_tlx" and value is not None
    )
