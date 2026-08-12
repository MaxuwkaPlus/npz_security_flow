"""Классификация применённых команд внутри шага симуляции."""

from collections.abc import Sequence

from sqlalchemy import select

from app.domain.classification import (
    AppliedAction,
    EffectRule,
    classify_effect,
    classify_on_apply,
)
from app.domain.commands import ActionStatus
from app.domain.twin import PlantState
from app.infrastructure.db.models import ExpectedActionRule, OperatorAction, TrainingSession
from app.infrastructure.db.unit_of_work import UnitOfWork

CORRECTIVE_ACTION_STEP = "corrective_action"


async def effect_rule(uow: UnitOfWork, scenario_version_id: str) -> EffectRule | None:
    """Правило подтверждения эффекта корректирующего шага эталонной последовательности."""

    query = select(ExpectedActionRule).where(
        ExpectedActionRule.scenario_version_id == scenario_version_id,
        ExpectedActionRule.action_type == CORRECTIVE_ACTION_STEP,
    )
    row = await uow.session.scalar(query)
    if row is None:
        return None
    return EffectRule.from_json(row.expected_effect_json, row.verification_rule_json)


async def classify_applied(
    uow: UnitOfWork,
    training_session: TrainingSession,
    actions: Sequence[OperatorAction],
    before: PlantState,
    after: PlantState,
    corrective_action_type: str,
    effect: EffectRule | None,
    has_diagnosis: bool,
) -> None:
    """Первый приём: повтор, нарушение порядка и заведомо неэффективное воздействие."""

    if not actions:
        return
    previous = await _previous_actions(uow, training_session.id, exclude={item.id for item in actions})
    removed_root_cause = after.corrected and not before.corrected

    for action in actions:
        if action.classification is not None:
            # Опасная компенсация определена правилом технолога и не пересматривается.
            continue
        verdict = classify_on_apply(
            _as_applied(action),
            is_corrective_type=action.action_type == corrective_action_type,
            removed_root_cause=removed_root_cause,
            diagnosis_submitted=has_diagnosis,
            previous_actions=previous,
            effect=effect,
        )
        action.requires_verification = verdict.requires_verification
        if verdict.classification is not None:
            action.classification = verdict.classification
            uow.sessions.append_event(
                training_session,
                "action_classified",
                "operator_action",
                {"action_type": action.action_type, "classification": verdict.classification.value},
                aggregate_id=action.id,
            )
        elif verdict.evaluation_window_ms is not None:
            action.evaluation_pending_until_ms = training_session.sim_time_ms + verdict.evaluation_window_ms


async def evaluate_pending_effects(
    uow: UnitOfWork,
    training_session: TrainingSession,
    metrics: dict[str, float],
    effect: EffectRule | None,
) -> None:
    """Второй приём: окно наблюдения истекло, эффект команды известен."""

    query = select(OperatorAction).where(
        OperatorAction.session_id == training_session.id,
        OperatorAction.classification.is_(None),
        OperatorAction.evaluation_pending_until_ms.is_not(None),
        OperatorAction.evaluation_pending_until_ms <= training_session.sim_time_ms,
    )
    for action in (await uow.session.scalars(query)).all():
        classification = classify_effect(effect, metrics)
        action.classification = classification
        uow.sessions.append_event(
            training_session,
            "action_classified",
            "operator_action",
            {"action_type": action.action_type, "classification": classification.value},
            aggregate_id=action.id,
        )


async def _previous_actions(uow: UnitOfWork, session_id: str, exclude: set[str]) -> list[AppliedAction]:
    query = select(OperatorAction).where(
        OperatorAction.session_id == session_id,
        OperatorAction.status == ActionStatus.APPLIED,
    )
    return [
        _as_applied(action) for action in (await uow.session.scalars(query)).all() if action.id not in exclude
    ]


def _as_applied(action: OperatorAction) -> AppliedAction:
    return AppliedAction(
        action_type=action.action_type,
        target_code=action.target_code,
        value=dict(action.requested_value_json),
    )
