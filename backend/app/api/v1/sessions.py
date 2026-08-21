from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import PrincipalDep, SessionRunnerDep, UnitOfWorkDep, require
from app.api.v1.schemas.actions import ActionResponse, SubmitActionRequest
from app.api.v1.schemas.alarms import AcknowledgeAlarmRequest, AlarmResponse
from app.api.v1.schemas.assessment import (
    NasaTlxRequest,
    NasaTlxResponseSchema,
    SagatCheckpointResponse,
    SagatResultResponse,
    SubmitSagatAnswersRequest,
)
from app.api.v1.schemas.observations import (
    DiagnosisResponse,
    ObservationResponse,
    RecordObservationRequest,
    SubmitDiagnosisRequest,
)
from app.api.v1.schemas.sessions import CreateSessionRequest, SessionCommandRequest, SessionResponse
from app.api.v1.tags import ACTIONS, ALARMS, ASSESSMENT, OBSERVATIONS, SESSION
from app.application.access import (
    authorize_session_assign,
    authorize_session_control,
    authorize_session_operate,
    authorize_session_read,
)
from app.application.actions import cancel_action, submit_action
from app.application.alarms import acknowledge_alarm, list_alarms
from app.application.assessment import current_checkpoint, submit_answers, submit_nasa_tlx
from app.application.observations import record_observation, submit_diagnosis
from app.application.runtime_config import sagat_policy
from app.application.sessions import (
    create_session,
    get_session_state,
    list_sessions,
    transition_session,
)
from app.core.errors import NotFoundError
from app.domain.rbac import Permission, Principal
from app.domain.sessions import SessionCommand, SessionStatus, is_terminal
from app.infrastructure.db.models import ScenarioVersion

# Тег указан у каждой ручки: теги роутера складывались бы с ними и группа дублировалась.
router = APIRouter(prefix="/sessions")

# Право завести прохождение проверяется зависимостью, а кому именно его назначают —
# уже в обработчике: инструктору можно любому оператору, самостоятельному обучаемому
# только себе. Управление ходом и работа за пультом сверяются с владельцем сессии.
CreatesSessions = Annotated[Principal, require(Permission.SESSION_CREATE)]


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=[SESSION],
    summary="Создать сессию",
)
async def post_session(
    payload: CreateSessionRequest, principal: CreatesSessions, uow: UnitOfWorkDep
) -> SessionResponse:
    """Заводит прохождение по выбранному сценарию и уровню сложности, фиксируя версии конфигурации.

    Сессия сразу готова к запуску. Скрытые параметры возмущения выбираются здесь же по seed
    и наружу не отдаются: причину оператор должен определить по приборам.
    """

    authorize_session_assign(principal, payload.operator_id)
    state = await create_session(
        uow,
        request_id=payload.request_id,
        operator_id=payload.operator_id,
        scenario_version_id=payload.scenario_version_id,
        level_no=payload.level_no,
        # Инструктора берём из токена: назначить сессию от чужого имени нельзя.
        # У самостоятельного прохождения ведущий и оператор совпадают.
        instructor_id=principal.subject_id,
        random_seed=payload.random_seed,
    )
    return SessionResponse.from_state(state)


@router.get("", response_model=list[SessionResponse], tags=[SESSION], summary="Список прохождений")
async def get_sessions(
    principal: PrincipalDep,
    uow: UnitOfWorkDep,
    operator_id: Annotated[str | None, Query(description="Фильтр по оператору")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SessionResponse]:
    """Прохождения от новых к старым.

    Обучаемому отдаются только назначенные ему сессии — иначе он не нашёл бы, куда
    садиться за пульт; инструктору и эксперту доступны все.
    """

    states = await list_sessions(uow, principal, operator_id=operator_id, limit=limit)
    return [SessionResponse.from_state(state) for state in states]


@router.get(
    "/{session_id}", response_model=SessionResponse, tags=[SESSION], summary="Сессия по идентификатору"
)
async def get_session(session_id: str, principal: PrincipalDep, uow: UnitOfWorkDep) -> SessionResponse:
    """Статус, этап и симуляционное время сессии. Отдаёт то же, что `/state`."""

    await authorize_session_read(uow, principal, session_id)
    return SessionResponse.from_state(await get_session_state(uow, session_id))


@router.get(
    "/{session_id}/state", response_model=SessionResponse, tags=[SESSION], summary="Текущее состояние сессии"
)
async def get_state(session_id: str, principal: PrincipalDep, uow: UnitOfWorkDep) -> SessionResponse:
    """Текущее состояние сессии; используется клиентом после разрыва WebSocket."""

    await authorize_session_read(uow, principal, session_id)
    return SessionResponse.from_state(await get_session_state(uow, session_id))


@router.post(
    "/{session_id}/actions",
    response_model=ActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=[ACTIONS],
    summary="Подать команду оператора",
)
async def post_action(
    session_id: str,
    payload: SubmitActionRequest,
    principal: PrincipalDep,
    runner: SessionRunnerDep,
) -> ActionResponse:
    """Принимает команду оператора: насосы, клапаны, промывочная вода, тепловая нагрузка печей.

    Ответ подтверждает только приём или отклонение — применит команду ближайший шаг симуляции,
    а её правильность оценивается позже и видна лишь в отчёте.
    """

    async with runner.exclusive(session_id) as uow:
        await authorize_session_operate(uow, principal, session_id)
        receipt = await submit_action(
            uow,
            session_id,
            request_id=payload.request_id,
            action_type=payload.action_type,
            target_code=payload.target_code,
            value=payload.value,
        )
    return ActionResponse.from_receipt(receipt)


@router.post(
    "/{session_id}/observations",
    response_model=ObservationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=[OBSERVATIONS],
    summary="Записать наблюдение",
)
async def post_observation(
    session_id: str,
    payload: RecordObservationRequest,
    principal: PrincipalDep,
    runner: SessionRunnerDep,
) -> ObservationResponse:
    """Фиксирует явную проверку участка оператором: осмотр узла, сравнение расходов, заявление
    об отклонении, проверку последствий после воздействия.

    Осмотр — обязательная часть работы: без нужных наблюдений этап не закрывается, а проверки
    последствий по цепочке влияют на итог прохождения.
    """

    async with runner.exclusive(session_id) as uow:
        await authorize_session_operate(uow, principal, session_id)
        receipt = await record_observation(
            uow,
            session_id,
            request_id=payload.request_id,
            observation_type=payload.observation_type,
            target_code=payload.target_code,
            payload=payload.payload,
        )
    return ObservationResponse.from_receipt(receipt)


@router.post(
    "/{session_id}/diagnoses",
    response_model=DiagnosisResponse,
    status_code=status.HTTP_201_CREATED,
    tags=[OBSERVATIONS],
    summary="Заявить диагноз",
)
async def post_diagnosis(
    session_id: str,
    payload: SubmitDiagnosisRequest,
    principal: PrincipalDep,
    runner: SessionRunnerDep,
) -> DiagnosisResponse:
    """Оператор называет затронутый участок, характер отклонения и предполагаемую первопричину.

    Правильность в ответе не сообщается — иначе тренажёр подсказывал бы в моменте; она попадает
    только в итоговый отчёт.
    """

    async with runner.exclusive(session_id) as uow:
        await authorize_session_operate(uow, principal, session_id)
        receipt = await submit_diagnosis(
            uow,
            session_id,
            request_id=payload.request_id,
            affected_area_code=payload.affected_area_code,
            deviation_code=payload.deviation_code,
            suspected_cause_code=payload.suspected_cause_code,
            confidence=payload.confidence,
        )
    return DiagnosisResponse.from_receipt(receipt)


@router.get(
    "/{session_id}/sagat/current",
    response_model=SagatCheckpointResponse | None,
    tags=[ASSESSMENT],
    summary="Открытая контрольная точка SAGAT",
)
async def get_current_sagat(
    session_id: str, principal: PrincipalDep, uow: UnitOfWorkDep
) -> SagatCheckpointResponse | None:
    """Открытая контрольная точка ситуационной осведомлённости или ничего.

    Вопросы приходят без эталонных ответов: эталон вычисляется на сервере из состояния установки
    на момент вопроса. Симуляция при этом не останавливается.
    """

    await authorize_session_read(uow, principal, session_id)
    scenario = await _scenario_of(uow, session_id)
    view = await current_checkpoint(uow, session_id, sagat_policy(scenario))
    return None if view is None else SagatCheckpointResponse.from_view(view)


@router.post(
    "/{session_id}/sagat/{checkpoint_id}/answers",
    response_model=SagatResultResponse,
    tags=[ASSESSMENT],
    summary="Ответить на вопросы SAGAT",
)
async def post_sagat_answers(
    session_id: str,
    checkpoint_id: str,
    payload: SubmitSagatAnswersRequest,
    principal: PrincipalDep,
    runner: SessionRunnerDep,
) -> SagatResultResponse:
    """Принимает ответы оператора и сразу оценивает их, сверяя с фактическим состоянием установки.

    Неполное понимание отличается от неверного: например, «без изменений» вместо реального
    тренда даёт половину балла, а противоположный тренд — ноль.
    """

    async with runner.exclusive(session_id) as uow:
        await authorize_session_operate(uow, principal, session_id)
        scenario = await _scenario_of(uow, session_id)
        result = await submit_answers(uow, session_id, checkpoint_id, payload.answers, sagat_policy(scenario))
    return SagatResultResponse.from_result(result)


@router.post(
    "/{session_id}/nasa-tlx",
    response_model=NasaTlxResponseSchema,
    status_code=status.HTTP_201_CREATED,
    tags=[ASSESSMENT],
    summary="Анкета субъективной нагрузки NASA-TLX",
)
async def post_nasa_tlx(
    session_id: str,
    payload: NasaTlxRequest,
    principal: PrincipalDep,
    runner: SessionRunnerDep,
) -> NasaTlxResponseSchema:
    """Шесть шкал субъективной нагрузки, заполняются после прохождения и только один раз.

    Показатель хранится отдельно и на квалификационную оценку не влияет: это самооценка
    оператора, а не результат его работы.
    """

    async with runner.exclusive(session_id) as uow:
        await authorize_session_operate(uow, principal, session_id)
        response = await submit_nasa_tlx(uow, session_id, payload.model_dump())
    return NasaTlxResponseSchema.from_model(response)


@router.post(
    "/{session_id}/actions/{action_id}/cancel",
    response_model=ActionResponse,
    tags=[ACTIONS],
    summary="Отменить команду",
)
async def post_action_cancel(
    session_id: str, action_id: str, principal: PrincipalDep, runner: SessionRunnerDep
) -> ActionResponse:
    """Отзывает команду, которую ещё не применил очередной шаг симуляции.

    Применённую отменить уже нельзя — только скомпенсировать другой командой, как на реальной
    установке.
    """

    async with runner.exclusive(session_id) as uow:
        await authorize_session_operate(uow, principal, session_id)
        receipt = await cancel_action(uow, session_id, action_id)
    return ActionResponse.from_receipt(receipt)


@router.get(
    "/{session_id}/alarms", response_model=list[AlarmResponse], tags=[ALARMS], summary="Активные тревоги"
)
async def get_alarms(session_id: str, principal: PrincipalDep, uow: UnitOfWorkDep) -> list[AlarmResponse]:
    """Активные тревоги сессии; используется клиентом при переподключении.

    В обычной работе изменения приходят по WebSocket, эта ручка нужна для восстановления картины.
    """

    await authorize_session_read(uow, principal, session_id)
    return [AlarmResponse.from_view(view) for view in await list_alarms(uow, session_id)]


@router.post(
    "/{session_id}/alarms/{alarm_id}/acknowledge",
    response_model=AlarmResponse,
    tags=[ALARMS],
    summary="Квитировать тревогу",
)
async def post_alarm_acknowledge(
    session_id: str,
    alarm_id: str,
    payload: AcknowledgeAlarmRequest,
    principal: PrincipalDep,
    runner: SessionRunnerDep,
) -> AlarmResponse:
    """Отмечает, что оператор увидел тревогу.

    Тревога от этого не гаснет — она снимется сама, когда исчезнет причина, — но оставленные
    без подтверждения тревоги снижают оценку безопасности.
    """

    async with runner.exclusive(session_id) as uow:
        training_session = await authorize_session_operate(uow, principal, session_id)
        view = await acknowledge_alarm(uow, session_id, alarm_id, operator_id=training_session.operator_id)
    return AlarmResponse.from_view(view)


@router.post(
    "/{session_id}/start", response_model=SessionResponse, tags=[SESSION], summary="Запустить сессию"
)
async def post_start(
    session_id: str,
    payload: SessionCommandRequest,
    principal: PrincipalDep,
    runner: SessionRunnerDep,
) -> SessionResponse:
    """Переводит сессию в `running` и запускает фоновую симуляцию.

    С этого момента идёт симуляционное время и принимаются команды оператора.
    """

    return await _transition(runner, principal, session_id, SessionCommand.START, payload)


@router.post(
    "/{session_id}/pause", response_model=SessionResponse, tags=[SESSION], summary="Поставить на паузу"
)
async def post_pause(
    session_id: str,
    payload: SessionCommandRequest,
    principal: PrincipalDep,
    runner: SessionRunnerDep,
) -> SessionResponse:
    """Останавливает симуляционное время — например, чтобы инструктор разобрал ситуацию.

    Команды и наблюдения оператора на паузе не принимаются.
    """

    return await _transition(runner, principal, session_id, SessionCommand.PAUSE, payload)


@router.post(
    "/{session_id}/resume", response_model=SessionResponse, tags=[SESSION], summary="Продолжить сессию"
)
async def post_resume(
    session_id: str,
    payload: SessionCommandRequest,
    principal: PrincipalDep,
    runner: SessionRunnerDep,
) -> SessionResponse:
    """Возобновляет ход симуляционного времени после паузы; развитие обстановки продолжается
    с того места, где было остановлено."""

    return await _transition(runner, principal, session_id, SessionCommand.RESUME, payload)


@router.post("/{session_id}/abort", response_model=SessionResponse, tags=[SESSION], summary="Прервать сессию")
async def post_abort(
    session_id: str,
    payload: SessionCommandRequest,
    principal: PrincipalDep,
    runner: SessionRunnerDep,
) -> SessionResponse:
    """Досрочно завершает прохождение с итогом «прервано»; квалификационная оценка не считается.

    Действие необратимо: продолжить прерванную сессию нельзя, нужно создавать новую.
    """

    return await _transition(runner, principal, session_id, SessionCommand.ABORT, payload)


async def _transition(
    runner: SessionRunnerDep,
    principal: Principal,
    session_id: str,
    command: SessionCommand,
    payload: SessionCommandRequest,
) -> SessionResponse:
    # Транзакция команды выполняется внутри блокировки сессии и завершается до выхода
    # из блока: тик и команда никогда не пишут состояние одной сессии одновременно.
    # Владелец проверяется здесь же — читать сессию дважды незачем.
    async with runner.exclusive(session_id) as uow:
        await authorize_session_control(uow, principal, session_id)
        state = await transition_session(
            uow,
            session_id,
            command,
            request_id=payload.request_id,
            expected_version=payload.expected_version,
        )

    # Симуляцию ведёт фоновая задача. На паузе она остаётся живой, чтобы продолжение
    # не требовало перезапуска, а в терминальном состоянии освобождается сразу.
    if state.status is SessionStatus.RUNNING:
        runner.start(session_id)
    elif is_terminal(state.status):
        await runner.stop(session_id)
    return SessionResponse.from_state(state)


async def _scenario_of(uow: UnitOfWorkDep, session_id: str) -> ScenarioVersion:
    training_session = await uow.sessions.get(session_id)
    if training_session is None:
        raise NotFoundError("SESSION_NOT_FOUND", "Сессия не найдена")
    scenario = await uow.session.get(ScenarioVersion, training_session.scenario_version_id)
    if scenario is None:
        raise NotFoundError("SCENARIO_NOT_FOUND", "Версия сценария сессии не найдена")
    return scenario
