from sqlalchemy import select

from app.application.actions import submit_action
from app.application.alarms import acknowledge_alarm, list_alarms
from app.application.sessions import create_session, transition_session
from app.application.tick import run_tick
from app.domain.sessions import SessionCommand
from app.domain.twin import START_FEED_PUMP
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import ScenarioVersion, SessionAlarm, SessionEvent, TrainingSession
from app.infrastructure.db.unit_of_work import UnitOfWork
from tests.conftest import SeededConfiguration

# Возмущение по конфигурации начинается около 3060 с, развивается 360 с. В тесте оба
# срока сокращены, чтобы не прогонять час симуляционного времени.
DISTURBANCE_ONSET_DELAY_MS = 0
# Возмущение вводится после подтверждения устойчивого режима. Здесь оно взводится
# напрямую: тест проверяет движок тревог, а не прохождение всех этапов сценария.
DISTURBANCE_ARMED_AT_MS = 300_000
DISTURBANCE_RAMP_MS = 60_000
# Прогрев теплообменной цепочки тоже ускорен: иначе температура выходит на предел
# только к концу часа, и проверка L3 стоила бы тысяч тиков.
WARMUP_TIME_CONSTANT_MS = 60_000


async def prepared_session(database: Database, configuration: SeededConfiguration) -> str:
    async with database.session_factory() as session, session.begin():
        scenario = await session.get(ScenarioVersion, configuration.scenario_version_id)
        assert scenario is not None
        config = dict(scenario.config_json)
        config["process_model"] = config["process_model"] | {
            "warmup_time_constant_ms": WARMUP_TIME_CONSTANT_MS
        }
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
        disturbance["onset_delay_ms"] = DISTURBANCE_ONSET_DELAY_MS
        disturbance["development"] = disturbance["development"] | {"ramp_duration_ms": DISTURBANCE_RAMP_MS}
        hidden["disturbance"] = disturbance
        training_session.hidden_runtime_config_json = hidden

    async with UnitOfWork(database.session_factory) as uow:
        await transition_session(uow, state.id, SessionCommand.START, request_id="start-1")
        await submit_action(
            uow, state.id, request_id="pump-1", action_type=START_FEED_PUMP, target_code="N-1"
        )
        training_session = await uow.sessions.get(state.id)
        assert training_session is not None
        runtime = dict(training_session.runtime_state_json)
        runtime["stage"] = runtime["stage"] | {"disturbance_armed_at_ms": DISTURBANCE_ARMED_AT_MS}
        training_session.runtime_state_json = runtime
    return state.id


async def tick(database: Database, session_id: str, times: int) -> None:
    for _ in range(times):
        async with UnitOfWork(database.session_factory) as uow:
            await run_tick(uow, session_id)


async def alarms_of(database: Database, session_id: str) -> list[SessionAlarm]:
    """Технологические тревоги сессии. Второстепенные помехи здесь не учитываются."""

    async with database.session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(SessionAlarm)
                    .where(
                        SessionAlarm.session_id == session_id,
                        SessionAlarm.is_nuisance.is_(False),
                    )
                    .order_by(SessionAlarm.started_sim_time_ms)
                )
            ).all()
        )


async def test_stable_plant_raises_no_process_alarms(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await prepared_session(database, configuration)

    await tick(database, session_id, times=250)

    assert await alarms_of(database, session_id) == []


async def test_developing_disturbance_raises_escalating_alarms(
    database: Database, configuration: SeededConfiguration
) -> None:
    """Сначала отклонение расхода, затем рассогласование потоков и температура."""

    session_id = await prepared_session(database, configuration)

    await tick(database, session_id, times=700)

    raised = [(alarm.alarm_code, alarm.level) for alarm in await alarms_of(database, session_id)]
    assert ("flow_deviation_branch", "L1") in raised
    assert ("feed_flow_imbalance", "L2") in raised
    assert ("t11_temperature_deviation", "L3") in raised
    assert ("elou_load_imbalance", "L4") in raised
    # Правила К-1, печей и К-2 молчат: эти участки моделируются следующими шагами.
    assert not {code for code, _ in raised} & {
        "k1_feed_deviation",
        "unsafe_furnace_heat_to_feed",
        "k2_critical_instability",
    }


async def test_alarm_appears_only_after_activation_delay(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await prepared_session(database, configuration)

    # Условие включения возникает только после начала возмущения на 300-й секунде.
    await tick(database, session_id, times=305)
    early = await alarms_of(database, session_id)
    await tick(database, session_id, times=115)
    later = await alarms_of(database, session_id)

    assert early == []
    first = later[0]
    assert first.alarm_code == "flow_deviation_branch"
    assert first.started_sim_time_ms > DISTURBANCE_ARMED_AT_MS


async def test_correct_action_clears_alarms_through_the_process(
    database: Database, configuration: SeededConfiguration
) -> None:
    """Оператор устранил причину — вторичные тревоги снимаются сами, без ручного удаления."""

    session_id = await prepared_session(database, configuration)
    await tick(database, session_id, times=700)

    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
        assert stored is not None
        correct_action = stored.hidden_runtime_config_json["disturbance"]["recovery"]["correct_action_type"]
        target_branch = stored.hidden_runtime_config_json["disturbance"]["target_branch"]

    target = "N-1A" if correct_action == "switch_to_standby_pump" else f"FRC-40{3 + target_branch}"
    async with UnitOfWork(database.session_factory) as uow:
        await submit_action(
            uow, session_id, request_id="fix-1", action_type=correct_action, target_code=target
        )
    await tick(database, session_id, times=600)

    active = [
        alarm.alarm_code for alarm in await alarms_of(database, session_id) if not alarm.cleared_sim_time_ms
    ]
    assert active == []


async def test_acknowledge_is_idempotent(database: Database, configuration: SeededConfiguration) -> None:
    session_id = await prepared_session(database, configuration)
    await tick(database, session_id, times=420)
    alarm_id = (await alarms_of(database, session_id))[0].id

    async with UnitOfWork(database.session_factory) as uow:
        first = await acknowledge_alarm(uow, session_id, alarm_id, operator_id="operator-1")
    async with UnitOfWork(database.session_factory) as uow:
        second = await acknowledge_alarm(uow, session_id, alarm_id, operator_id="operator-1")

    assert first.state == "active_acknowledged"
    assert first.acknowledged_sim_time_ms == second.acknowledged_sim_time_ms

    async with database.session_factory() as session:
        events = (
            await session.scalars(select(SessionEvent).where(SessionEvent.event_type == "alarm_acknowledged"))
        ).all()
    assert len(events) == 1


async def test_active_alarm_list_exposes_no_hidden_fields(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await prepared_session(database, configuration)
    await tick(database, session_id, times=420)

    async with UnitOfWork(database.session_factory) as uow:
        views = [view for view in await list_alarms(uow, session_id) if not view.is_nuisance]

    assert views[0].alarm_code == "flow_deviation_branch"
    assert views[0].equipment_code == "FEED-SYSTEM"
    assert all(view.state == "active_unacknowledged" for view in views)


async def test_nuisance_alarms_appear_and_clear_by_themselves(
    database: Database, configuration: SeededConfiguration
) -> None:
    """Второстепенные тревоги создают фон, гаснут сами и не смешиваются с технологическими."""

    session_id = await prepared_session(database, configuration)

    await tick(database, session_id, times=250)

    async with database.session_factory() as session:
        nuisance = (
            await session.scalars(
                select(SessionAlarm).where(
                    SessionAlarm.session_id == session_id,
                    SessionAlarm.is_nuisance.is_(True),
                )
            )
        ).all()

    assert nuisance, "на первом уровне сложности фон помех всё равно должен появляться"
    assert {alarm.level for alarm in nuisance} == {"L0"}
    assert {alarm.equipment_code for alarm in nuisance} == {"AUX-SYSTEM"}
    assert await alarms_of(database, session_id) == []

    await tick(database, session_id, times=200)
    async with database.session_factory() as session:
        first = await session.get(SessionAlarm, nuisance[0].id)
    assert first is not None
    assert first.cleared_sim_time_ms is not None
