"""Сквозная проверка цепочки: возмущение доходит от сырьевой ветви до К-2.

Постоянные времени и момент возмущения в тестовой конфигурации сокращены. Модель та же,
иначе один прогон занимал бы час симуляционного времени и десятки тысяч тиков.
"""

from sqlalchemy import select

from app.application.actions import submit_action
from app.application.sessions import create_session, transition_session
from app.application.tick import run_tick
from app.domain.downstream import SET_FURNACE_HEAT_LOAD, SET_WASH_WATER, START_TRANSFER_PUMP
from app.domain.safety import DANGEROUS_HEAT_COMPENSATION
from app.domain.sessions import SessionCommand
from app.domain.twin import START_FEED_PUMP
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import (
    OperatorAction,
    ProcessSnapshot,
    ScenarioVersion,
    SessionAlarm,
    SessionEvent,
)
from app.infrastructure.db.unit_of_work import UnitOfWork
from tests.conftest import SeededConfiguration

DISTURBANCE_ONSET_MS = 600_000
DISTURBANCE_RAMP_MS = 60_000
FAST_MODEL = {
    "warmup_time_constant_ms": 30_000,
    "flow_time_constant_ms": 20_000,
    "downstream": {
        "elou_load_time_constant_ms": 20_000,
        "elou_stage2_time_constant_ms": 10_000,
        "elou_level_time_constant_ms": 10_000,
        "e15_load_time_constant_ms": 10_000,
        "e15_level_time_constant_ms": 10_000,
        "k1_load_time_constant_ms": 10_000,
        "k1_time_constant_ms": 20_000,
        "furnace_time_constant_ms": 20_000,
        "k2_load_time_constant_ms": 30_000,
        "k2_time_constant_ms": 30_000,
        "product_time_constant_ms": 30_000,
    },
}


async def prepare(database: Database, configuration: SeededConfiguration) -> str:
    async with database.session_factory() as session, session.begin():
        scenario = await session.get(ScenarioVersion, configuration.scenario_version_id)
        assert scenario is not None
        config = dict(scenario.config_json)
        model = dict(config["process_model"])
        model.update({key: value for key, value in FAST_MODEL.items() if key != "downstream"})
        model["downstream"] = model["downstream"] | FAST_MODEL["downstream"]
        config["process_model"] = model
        scenario.config_json = config

    async with UnitOfWork(database.session_factory) as uow:
        state = await create_session(
            uow,
            request_id="create-1",
            operator_id="operator-1",
            scenario_version_id=configuration.scenario_version_id,
            level_no=1,
            random_seed=42,
        )
        training_session = await uow.sessions.get(state.id)
        assert training_session is not None
        hidden = dict(training_session.hidden_runtime_config_json)
        disturbance = dict(hidden["disturbance"])
        disturbance["onset_sim_time_ms"] = DISTURBANCE_ONSET_MS
        disturbance["development"] = disturbance["development"] | {"ramp_duration_ms": DISTURBANCE_RAMP_MS}
        hidden["disturbance"] = disturbance
        training_session.hidden_runtime_config_json = hidden

    async with UnitOfWork(database.session_factory) as uow:
        await transition_session(uow, state.id, SessionCommand.START, request_id="start-1")
    return state.id


async def act(
    database: Database, session_id: str, request_id: str, action_type: str, target: str, **value: float
) -> None:
    async with UnitOfWork(database.session_factory) as uow:
        await submit_action(
            uow,
            session_id,
            request_id=request_id,
            action_type=action_type,
            target_code=target,
            value=value,
        )


async def tick(database: Database, session_id: str, times: int) -> None:
    for _ in range(times):
        async with UnitOfWork(database.session_factory) as uow:
            await run_tick(uow, session_id)


async def start_plant(database: Database, configuration: SeededConfiguration) -> str:
    """Пуск: насос, промывочная вода, откачка из Е-15, розжиг печей — и выход на режим."""

    session_id = await prepare(database, configuration)
    await act(database, session_id, "pump", START_FEED_PUMP, "N-1")
    await act(database, session_id, "water", SET_WASH_WATER, "ELOU", ratio=0.075)
    await act(database, session_id, "n20", START_TRANSFER_PUMP, "N-20")
    await tick(database, session_id, times=200)
    # Печи зажигаются, когда сырьё уже дошло: соотношение тепла и расхода должно быть в норме.
    await act(database, session_id, "fire", SET_FURNACE_HEAT_LOAD, "FURNACES", heat_load_pct=100.0)
    await tick(database, session_id, times=300)
    return session_id


async def latest_snapshot(database: Database, session_id: str) -> ProcessSnapshot:
    async with database.session_factory() as session:
        snapshot = await session.scalar(
            select(ProcessSnapshot)
            .where(ProcessSnapshot.session_id == session_id)
            .order_by(ProcessSnapshot.sim_time_ms.desc())
            .limit(1)
        )
    assert snapshot is not None
    return snapshot


async def process_alarms(database: Database, session_id: str) -> list[SessionAlarm]:
    """Только технологические тревоги: второстепенные помехи — методический шум."""

    async with database.session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(SessionAlarm).where(
                        SessionAlarm.session_id == session_id,
                        SessionAlarm.is_nuisance.is_(False),
                    )
                )
            ).all()
        )


async def alarm_levels(database: Database, session_id: str) -> set[str]:
    return {alarm.level for alarm in await process_alarms(database, session_id)}


async def alarm_codes(database: Database, session_id: str) -> set[str]:
    return {alarm.alarm_code for alarm in await process_alarms(database, session_id)}


async def test_started_plant_reaches_normal_regime_end_to_end(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_plant(database, configuration)

    values = (await latest_snapshot(database, session_id)).visible_values_json
    assert values["elou_stage1_min_level_mm"] > 3700.0
    assert 40.0 < values["e15_level_pct"] < 60.0
    assert values["n20_state"] == "RUNNING"
    assert values["k1_bottom_temp_c"] < 280.0
    assert values["k2_top_temp_c"] < 148.0
    assert values["k2_stability_index"] > 0.85
    assert values["product_flow_stability_index"] > 0.85
    assert await alarm_codes(database, session_id) == set()


async def test_disturbance_escalates_through_the_whole_chain(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_plant(database, configuration)

    await tick(database, session_id, times=900)

    levels = await alarm_levels(database, session_id)
    assert {"L1", "L2", "L3", "L4", "L5"} <= levels

    values = (await latest_snapshot(database, session_id)).visible_values_json
    assert values["k1_feed_flow_ratio"] < 0.91
    assert values["k2_stability_index"] < 0.85


async def test_dangerous_heat_compensation_is_recorded(
    database: Database, configuration: SeededConfiguration
) -> None:
    """Оператор гасит симптом нагрузкой печей — это фиксируется отдельным событием."""

    session_id = await start_plant(database, configuration)
    await tick(database, session_id, times=300)

    await act(database, session_id, "heat", SET_FURNACE_HEAT_LOAD, "FURNACES", heat_load_pct=125.0)
    await tick(database, session_id, times=300)

    async with database.session_factory() as session:
        events = (
            await session.scalars(
                select(SessionEvent).where(SessionEvent.event_type == DANGEROUS_HEAT_COMPENSATION)
            )
        ).all()
        action = await session.scalar(select(OperatorAction).where(OperatorAction.request_id == "heat"))

    assert len(events) == 1
    assert action is not None
    assert action.classification == "dangerous"
    values = (await latest_snapshot(database, session_id)).visible_values_json
    assert values["furnace_heat_to_feed_ratio"] > 1.25


async def test_lowering_heat_load_is_not_dangerous(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_plant(database, configuration)
    await tick(database, session_id, times=300)

    await act(database, session_id, "heat", SET_FURNACE_HEAT_LOAD, "FURNACES", heat_load_pct=88.0)
    await tick(database, session_id, times=300)

    async with database.session_factory() as session:
        events = (
            await session.scalars(
                select(SessionEvent).where(SessionEvent.event_type == DANGEROUS_HEAT_COMPENSATION)
            )
        ).all()
    assert events == []
