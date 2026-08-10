import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.domain.sessions import SessionStatus
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import ProcessSnapshot, SessionEvent, TrainingSession
from app.infrastructure.db.unit_of_work import UnitOfWork
from app.infrastructure.repositories.sessions import state_hash
from tests.conftest import SeededConfiguration


def make_session(configuration: SeededConfiguration, seed: int = 42) -> TrainingSession:
    return TrainingSession(
        operator_id="operator-1",
        scenario_version_id=configuration.scenario_version_id,
        scenario_level_id=configuration.level_ids[1],
        scoring_policy_version_id=configuration.scoring_policy_version_id,
        status=SessionStatus.CREATED,
        current_stage_code="precheck",
        random_seed=seed,
        hidden_runtime_config_json={"target_branch": 2},
    )


async def create_session(database: Database, configuration: SeededConfiguration) -> str:
    async with UnitOfWork(database.session_factory) as uow:
        training_session = make_session(configuration)
        uow.sessions.add(training_session)
        await uow.flush()
        return training_session.id


async def test_events_and_snapshots_share_one_monotonic_sequence(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await create_session(database, configuration)

    async with UnitOfWork(database.session_factory) as uow:
        training_session = await uow.sessions.get(session_id)
        assert training_session is not None
        uow.sessions.append_event(training_session, "session_started", "session", {})
        uow.sessions.add_snapshot(training_session, {"total_feed_flow_tph": 0.0}, {}, {})
        uow.sessions.append_event(training_session, "stage_changed", "session", {"to": "feed_preparation"})

    async with database.session_factory() as session:
        events = (await session.scalars(select(SessionEvent).order_by(SessionEvent.sequence_no))).all()
        snapshots = (await session.scalars(select(ProcessSnapshot))).all()

    assert [event.sequence_no for event in events] == [1, 3]
    assert [snapshot.sequence_no for snapshot in snapshots] == [2]


async def test_duplicate_sequence_number_is_rejected(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await create_session(database, configuration)

    with pytest.raises(IntegrityError):
        async with UnitOfWork(database.session_factory) as uow:
            training_session = await uow.sessions.get(session_id)
            assert training_session is not None
            uow.sessions.append_event(training_session, "session_started", "session", {})
            # Ручной откат счётчика имитирует гонку двух писателей одной сессии.
            training_session.last_sequence_no -= 1
            uow.sessions.append_event(training_session, "session_started", "session", {})


async def test_event_of_unknown_session_is_rejected_by_foreign_key(database: Database) -> None:
    with pytest.raises(IntegrityError):
        async with UnitOfWork(database.session_factory) as uow:
            uow.session.add(
                SessionEvent(
                    session_id="00000000-0000-0000-0000-000000000000",
                    sequence_no=1,
                    sim_time_ms=0,
                    event_type="session_started",
                    aggregate_type="session",
                    payload_json={},
                )
            )


async def test_stale_version_loses_the_write(database: Database, configuration: SeededConfiguration) -> None:
    """Optimistic locking: второй писатель с устаревшей версией не должен затереть первого."""

    session_id = await create_session(database, configuration)

    async with database.session_factory() as first, database.session_factory() as second:
        first_copy = await first.get(TrainingSession, session_id)
        second_copy = await second.get(TrainingSession, session_id)
        assert first_copy is not None and second_copy is not None

        first_copy.sim_time_ms = 1_000
        await first.commit()

        second_copy.sim_time_ms = 2_000
        with pytest.raises(StaleDataError):
            await second.commit()

    async with database.session_factory() as session:
        stored = await session.get(TrainingSession, session_id)
        assert stored is not None
        assert stored.sim_time_ms == 1_000
        assert stored.version_no == 2


async def test_snapshot_hash_depends_only_on_state(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await create_session(database, configuration)

    async with UnitOfWork(database.session_factory) as uow:
        training_session = await uow.sessions.get(session_id)
        assert training_session is not None
        snapshot = uow.sessions.add_snapshot(training_session, {"flow": 100.0}, {"ratio": 1.0}, {"sev": 0.0})
        expected = state_hash({"visible": {"flow": 100.0}, "internal": {"sev": 0.0}})

    assert snapshot.state_hash == expected


async def test_rolled_back_unit_of_work_writes_nothing(
    database: Database, configuration: SeededConfiguration
) -> None:
    session_id = await create_session(database, configuration)

    with pytest.raises(RuntimeError, match="прервано"):
        async with UnitOfWork(database.session_factory) as uow:
            training_session = await uow.sessions.get(session_id)
            assert training_session is not None
            uow.sessions.append_event(training_session, "session_started", "session", {})
            raise RuntimeError("прервано на середине tick")

    async with database.session_factory() as session:
        events = (await session.scalars(select(SessionEvent))).all()
        stored = await session.get(TrainingSession, session_id)

    assert events == []
    assert stored is not None
    assert stored.last_sequence_no == 0
