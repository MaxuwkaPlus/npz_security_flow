"""Продвижение сессии по этапам сценария."""

from collections.abc import Mapping, Sequence

from sqlalchemy import select

from app.domain.rules import parse_rule
from app.domain.stages import Stage, StageDecision, evaluate_stage
from app.infrastructure.db.models import ScenarioStage, TrainingSession
from app.infrastructure.db.unit_of_work import UnitOfWork

# Обязательные проверки — это наблюдения оператора, они появятся вместе с
# фиксацией отклонения и диагнозом. Пока список выполненных проверок всегда пуст,
# поэтому такие этапы закрываются по timeout.
COMPLETED_CHECKS: frozenset[str] = frozenset()


async def load_stages(uow: UnitOfWork, scenario_version_id: str) -> list[Stage]:
    query = (
        select(ScenarioStage)
        .where(ScenarioStage.scenario_version_id == scenario_version_id)
        .order_by(ScenarioStage.order_no)
    )
    rows = (await uow.session.scalars(query)).all()
    return [
        Stage(
            code=row.code,
            order_no=row.order_no,
            success=parse_rule(row.success_rule_json),
            failure=parse_rule(row.failure_rule_json),
            timeout_ms=row.timeout_ms,
            required_checks=tuple(row.required_checks_json),
        )
        for row in rows
    ]


async def advance_stage(
    uow: UnitOfWork,
    training_session: TrainingSession,
    stages: Sequence[Stage],
    metrics: Mapping[str, float],
    holding_since_ms: int | None,
) -> StageDecision:
    """Закрывает текущий этап и открывает следующий. Возвращает решение движка."""

    current = next((stage for stage in stages if stage.code == training_session.current_stage_code), None)
    if current is None:
        return StageDecision(outcome=None, next_stage_code=None, holding_since_ms=None)

    entry = await uow.sessions.current_stage_entry(training_session.id)
    decision = evaluate_stage(
        current,
        stages,
        metrics,
        entered_sim_time_ms=entry.entered_sim_time_ms if entry else 0,
        sim_time_ms=training_session.sim_time_ms,
        holding_since_ms=holding_since_ms,
        completed_checks=COMPLETED_CHECKS,
    )
    if not decision.changed:
        return decision

    if entry is not None:
        entry.exited_sim_time_ms = training_session.sim_time_ms
        entry.outcome = decision.outcome.value if decision.outcome else None

    event = uow.sessions.append_event(
        training_session,
        "stage_changed",
        "stage",
        {
            "from": current.code,
            "to": decision.next_stage_code,
            "outcome": decision.outcome.value if decision.outcome else None,
        },
    )
    if entry is not None:
        await uow.flush()
        entry.transition_reason_event_id = event.id

    if decision.next_stage_code is not None:
        training_session.current_stage_code = decision.next_stage_code
        uow.sessions.open_stage(training_session, decision.next_stage_code)
    return decision
