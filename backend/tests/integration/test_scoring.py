"""Оценка прохождения на живой сессии: считается из журнала и воспроизводима."""

from sqlalchemy import select

from app.application.actions import submit_action
from app.application.observations import record_observation, submit_diagnosis
from app.application.scoring import calculate_scores
from app.application.sessions import create_session, transition_session
from app.application.tick import run_tick
from app.domain.downstream import SET_FURNACE_HEAT_LOAD, SET_WASH_WATER, START_TRANSFER_PUMP
from app.domain.sessions import SessionCommand
from app.domain.twin import START_FEED_PUMP
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import ScenarioVersion, ScoreEventRecord, SessionScore, TrainingSession
from app.infrastructure.db.unit_of_work import UnitOfWork
from tests.conftest import SeededConfiguration
from tests.support import speed_up_process_model


async def prepared(database: Database, configuration: SeededConfiguration) -> str:
    async with database.session_factory() as session, session.begin():
        scenario = await session.get(ScenarioVersion, configuration.scenario_version_id)
        assert scenario is not None
        scenario.config_json = speed_up_process_model(scenario.config_json)

    async with UnitOfWork(database.session_factory) as uow:
        state = await create_session(
            uow,
            request_id="create-1",
            operator_id="operator-1",
            scenario_version_id=configuration.scenario_version_id,
            level_no=1,
            random_seed=42,
        )
    async with UnitOfWork(database.session_factory) as uow:
        await transition_session(uow, state.id, SessionCommand.START, request_id="start-1")
    return state.id


async def act(
    database: Database, session_id: str, request_id: str, action_type: str, target: str, **value: float
) -> None:
    async with UnitOfWork(database.session_factory) as uow:
        await submit_action(
            uow, session_id, request_id=request_id, action_type=action_type, target_code=target, value=value
        )


async def observe(database: Database, session_id: str, request_id: str, kind: str, target: str) -> None:
    async with UnitOfWork(database.session_factory) as uow:
        await record_observation(
            uow, session_id, request_id=request_id, observation_type=kind, target_code=target
        )


async def tick(database: Database, session_id: str, times: int) -> None:
    for _ in range(times):
        async with UnitOfWork(database.session_factory) as uow:
            await run_tick(uow, session_id)


async def start_plant(database: Database, configuration: SeededConfiguration) -> str:
    session_id = await prepared(database, configuration)
    await act(database, session_id, "pump", START_FEED_PUMP, "N-1")
    await act(database, session_id, "water", SET_WASH_WATER, "ELOU", ratio=0.075)
    await act(database, session_id, "n20", START_TRANSFER_PUMP, "N-20")
    await tick(database, session_id, times=200)
    await act(database, session_id, "fire", SET_FURNACE_HEAT_LOAD, "FURNACES", heat_load_pct=100.0)
    await tick(database, session_id, times=400)
    return session_id


async def scores_of(database: Database, session_id: str) -> SessionScore:
    async with database.session_factory() as session:
        stored = await session.get(SessionScore, session_id)
    assert stored is not None
    return stored


async def test_scores_are_calculated_and_stored(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_plant(database, configuration)

    async with UnitOfWork(database.session_factory) as uow:
        scores = await calculate_scores(uow, session_id)

    stored = await scores_of(database, session_id)
    assert stored.resultiveness_score == scores.resultiveness
    assert 0.0 <= stored.resultiveness_score <= 100.0
    assert 0.0 <= stored.safety_score <= 100.0


async def test_every_score_event_names_its_rule(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_plant(database, configuration)

    async with UnitOfWork(database.session_factory) as uow:
        await calculate_scores(uow, session_id)

    async with database.session_factory() as session:
        events = (
            await session.scalars(select(ScoreEventRecord).where(ScoreEventRecord.session_id == session_id))
        ).all()
    assert events
    assert all(event.rule_code and event.reason for event in events)


async def test_recalculation_gives_the_same_result(
    database: Database, configuration: SeededConfiguration
) -> None:
    """Оценка выводится из журнала, поэтому пересчёт не меняет итог."""

    session_id = await start_plant(database, configuration)

    async with UnitOfWork(database.session_factory) as uow:
        first = await calculate_scores(uow, session_id)
    async with UnitOfWork(database.session_factory) as uow:
        second = await calculate_scores(uow, session_id)

    assert first == second

    async with database.session_factory() as session:
        events = (
            await session.scalars(select(ScoreEventRecord).where(ScoreEventRecord.session_id == session_id))
        ).all()
    # Пересчёт заменяет прежние записи, а не добавляет вторые.
    assert len(events) == len(first.events)


async def test_following_the_reference_sequence_raises_action_correctness(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_plant(database, configuration)
    await tick(database, session_id, times=600)

    async with UnitOfWork(database.session_factory) as uow:
        before = await calculate_scores(uow, session_id)

    await observe(database, session_id, "obs-1", "declare_deviation", "FEED-SYSTEM")
    await observe(database, session_id, "obs-2", "compare_flows", "FEED-SYSTEM")
    await observe(database, session_id, "obs-3", "inspect_pressure", "FEED-SYSTEM")
    await observe(database, session_id, "obs-4", "inspect_equipment", "N-1")
    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
        assert stored is not None
        hidden = stored.hidden_runtime_config_json["disturbance"]
    async with UnitOfWork(database.session_factory) as uow:
        await submit_diagnosis(
            uow,
            session_id,
            request_id="diag",
            affected_area_code="FEED-SYSTEM",
            deviation_code="branch_flow_loss",
            suspected_cause_code=hidden["cause_code"],
        )
    await tick(database, session_id, times=5)

    async with UnitOfWork(database.session_factory) as uow:
        after = await calculate_scores(uow, session_id)

    assert after.action_correctness > before.action_correctness


async def test_dangerous_compensation_lowers_safety(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await start_plant(database, configuration)
    await tick(database, session_id, times=300)

    async with UnitOfWork(database.session_factory) as uow:
        before = await calculate_scores(uow, session_id)

    await act(database, session_id, "heat", SET_FURNACE_HEAT_LOAD, "FURNACES", heat_load_pct=125.0)
    await tick(database, session_id, times=10)

    async with UnitOfWork(database.session_factory) as uow:
        after = await calculate_scores(uow, session_id)

    assert after.safety < before.safety
    assert after.resultiveness < before.resultiveness


async def test_completed_session_is_scored_automatically(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await prepared(database, configuration)

    async with database.session_factory() as session, session.begin():
        scenario = await session.get(ScenarioVersion, configuration.scenario_version_id)
        assert scenario is not None
        scenario.duration_ms = 20_000

    await tick(database, session_id, times=25)

    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
        score = await session.get(SessionScore, session_id)
    assert stored is not None and stored.status == "completed"
    assert score is not None
