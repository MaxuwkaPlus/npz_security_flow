"""Контракт доступа: кто и что может делать через API.

Матрица прав проверяется модульно (`tests/unit/test_rbac.py`), здесь — что она
действительно применяется на каждой ручке и что отказ попадает в журнал.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.conftest import SeededConfiguration, login_as


async def create_session(
    client: AsyncClient, configuration: SeededConfiguration, operator_id: str = "operator-1"
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/sessions",
        json={
            "request_id": str(uuid4()),
            "operator_id": operator_id,
            "scenario_version_id": configuration.scenario_version_id,
            "level_no": 1,
            "random_seed": 42,
        },
    )
    assert response.status_code == 201, response.text
    session: dict[str, Any] = response.json()
    return session


# --- аутентификация ----------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/scenarios"),
        ("post", "/api/v1/sessions"),
        ("get", "/api/v1/users"),
        ("get", "/api/v1/security-events"),
    ],
)
async def test_request_without_token_is_rejected(
    anonymous_client: AsyncClient, method: str, path: str
) -> None:
    response = await getattr(anonymous_client, method)(path)

    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "MISSING_TOKEN"
    assert set(error) == {"code", "message", "details", "request_id"}


async def test_invalid_token_is_rejected(anonymous_client: AsyncClient, accounts: dict[str, str]) -> None:
    response = await anonymous_client.get(
        "/api/v1/scenarios", headers={"authorization": "Bearer not-a-real-token"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


async def test_unknown_login_and_wrong_password_are_indistinguishable(
    anonymous_client: AsyncClient, accounts: dict[str, str], test_password: str
) -> None:
    """Иначе по ответу можно было бы собрать список существующих учётных записей."""

    unknown = await anonymous_client.post(
        "/api/v1/auth/login", json={"username": "нет-такого", "password": test_password}
    )
    wrong = await anonymous_client.post(
        "/api/v1/auth/login", json={"username": "operator-1", "password": "не тот пароль"}
    )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]


async def test_login_returns_roles_and_permissions(
    anonymous_client: AsyncClient, accounts: dict[str, str], test_password: str
) -> None:
    response = await anonymous_client.post(
        "/api/v1/auth/login", json={"username": "expert-1", "password": test_password}
    )

    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["roles"] == ["expert"]
    assert "report.read_any" in body["user"]["permissions"]
    assert "session.create" not in body["user"]["permissions"]


async def test_logout_invalidates_the_token(expert_client: AsyncClient) -> None:
    assert (await expert_client.post("/api/v1/auth/logout")).status_code == 204

    after = await expert_client.get("/api/v1/scenarios")

    assert after.status_code == 401
    assert after.json()["error"]["code"] == "INVALID_TOKEN"


# --- разделение прав ---------------------------------------------------


async def test_trainee_cannot_assign_a_session(
    trainee_client: AsyncClient, configuration: SeededConfiguration
) -> None:
    """«Запуск сценария» — право инструктора, обучаемый проходит назначенное."""

    response = await trainee_client.post(
        "/api/v1/sessions",
        json={
            "request_id": str(uuid4()),
            "operator_id": "operator-2",
            "scenario_version_id": configuration.scenario_version_id,
            "level_no": 1,
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["required_any_of"] == ["session.create"]


async def test_trainee_cannot_control_the_session_assigned_to_them(
    instructor_client: AsyncClient, trainee_client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session = await create_session(instructor_client, configuration, operator_id="operator-2")

    response = await trainee_client.post(
        f"/api/v1/sessions/{session['id']}/start", json={"request_id": str(uuid4())}
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["required_any_of"] == ["session.control"]


async def test_instructor_does_not_operate_the_console_instead_of_trainee(
    instructor_client: AsyncClient, configuration: SeededConfiguration
) -> None:
    """Иначе журнал перестал бы отвечать, чей навык проверяется."""

    session = await create_session(instructor_client, configuration, operator_id="operator-2")
    await instructor_client.post(f"/api/v1/sessions/{session['id']}/start", json={"request_id": str(uuid4())})

    response = await instructor_client.post(
        f"/api/v1/sessions/{session['id']}/actions",
        json={"request_id": str(uuid4()), "action_type": "start_feed_pump", "target_code": "N-1"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["required_any_of"] == ["session.operate"]


async def test_trainee_cannot_operate_a_session_of_another_operator(
    instructor_client: AsyncClient, trainee_client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session = await create_session(instructor_client, configuration, operator_id="operator-1")
    await instructor_client.post(f"/api/v1/sessions/{session['id']}/start", json={"request_id": str(uuid4())})

    response = await trainee_client.post(
        f"/api/v1/sessions/{session['id']}/actions",
        json={"request_id": str(uuid4()), "action_type": "start_feed_pump", "target_code": "N-1"},
    )

    assert response.status_code == 403


async def test_trainee_sees_own_session_but_not_a_foreign_one(
    instructor_client: AsyncClient, trainee_client: AsyncClient, configuration: SeededConfiguration
) -> None:
    own = await create_session(instructor_client, configuration, operator_id="operator-2")
    foreign = await create_session(instructor_client, configuration, operator_id="operator-1")

    assert (await trainee_client.get(f"/api/v1/sessions/{own['id']}")).status_code == 200
    assert (await trainee_client.get(f"/api/v1/sessions/{foreign['id']}")).status_code == 403


async def test_trainee_sees_own_report_but_not_a_foreign_one(
    instructor_client: AsyncClient, trainee_client: AsyncClient, configuration: SeededConfiguration
) -> None:
    own = await create_session(instructor_client, configuration, operator_id="operator-2")
    foreign = await create_session(instructor_client, configuration, operator_id="operator-1")

    assert (await trainee_client.get(f"/api/v1/sessions/{own['id']}/report")).status_code == 200
    assert (await trainee_client.get(f"/api/v1/sessions/{foreign['id']}/report")).status_code == 403


async def test_expert_reads_any_report_but_does_not_assign_training(
    instructor_client: AsyncClient, expert_client: AsyncClient, configuration: SeededConfiguration
) -> None:
    session = await create_session(instructor_client, configuration, operator_id="operator-1")

    assert (await expert_client.get(f"/api/v1/sessions/{session['id']}/report")).status_code == 200

    response = await expert_client.post(
        "/api/v1/sessions",
        json={
            "request_id": str(uuid4()),
            "operator_id": "operator-1",
            "scenario_version_id": configuration.scenario_version_id,
            "level_no": 1,
        },
    )
    assert response.status_code == 403


async def test_security_admin_investigates_without_reading_training_results(
    instructor_client: AsyncClient, security_client: AsyncClient, configuration: SeededConfiguration
) -> None:
    """Расследование доступа не требует содержания отчёта об обучении."""

    session = await create_session(instructor_client, configuration, operator_id="operator-1")

    assert (await security_client.get(f"/api/v1/sessions/{session['id']}")).status_code == 200
    assert (await security_client.get("/api/v1/security-events")).status_code == 200
    assert (await security_client.get(f"/api/v1/sessions/{session['id']}/report")).status_code == 403


async def test_audit_journal_is_closed_to_everyone_but_security_admin(
    instructor_client: AsyncClient, expert_client: AsyncClient, trainee_client: AsyncClient
) -> None:
    for client in (instructor_client, expert_client, trainee_client):
        response = await client.get("/api/v1/security-events")

        assert response.status_code == 403
        assert response.json()["error"]["details"]["required_any_of"] == ["audit.read"]


async def test_instructor_id_is_taken_from_the_token(
    instructor_client: AsyncClient, configuration: SeededConfiguration
) -> None:
    """Назначить сессию от чужого имени нельзя: поля в запросе нет."""

    session = await create_session(instructor_client, configuration, operator_id="operator-2")

    assert session["instructor_id"] == "instructor-1"


# --- журнал безопасности -----------------------------------------------


async def test_denied_access_is_recorded_for_investigation(
    trainee_client: AsyncClient, security_client: AsyncClient
) -> None:
    await trainee_client.get("/api/v1/security-events")

    events = (await security_client.get("/api/v1/security-events?event_type=access_denied")).json()

    assert events, "отказ в доступе должен попасть в журнал"
    denied = events[0]
    assert denied["actor_username"] == "operator-2"
    assert denied["outcome"] == "failure"
    assert denied["payload"]["permission"] == "audit.read"
    assert denied["target_id"] == "GET /api/v1/security-events"


async def test_failed_login_is_recorded_without_the_password(
    anonymous_client: AsyncClient, security_client: AsyncClient, accounts: dict[str, str]
) -> None:
    await anonymous_client.post(
        "/api/v1/auth/login", json={"username": "operator-1", "password": "не тот пароль"}
    )

    events = (await security_client.get("/api/v1/security-events?event_type=login")).json()
    failures = [event for event in events if event["outcome"] == "failure"]

    assert failures
    assert failures[0]["actor_username"] == "operator-1"
    assert "не тот пароль" not in str(failures[0])


# --- управление учётными записями --------------------------------------


async def test_only_account_manager_creates_users(
    instructor_client: AsyncClient, security_client: AsyncClient, test_password: str
) -> None:
    payload = {
        "username": "operator-9",
        "display_name": "Оператор Новиков",
        "password": test_password,
        "roles": ["trainee"],
    }

    assert (await instructor_client.post("/api/v1/users", json=payload)).status_code == 403

    created = await security_client.post("/api/v1/users", json=payload)
    assert created.status_code == 201
    assert created.json()["roles"] == ["trainee"]


async def test_role_of_the_next_cycle_cannot_be_granted_yet(
    security_client: AsyncClient, test_password: str
) -> None:
    response = await security_client.post(
        "/api/v1/users",
        json={
            "username": "author-1",
            "display_name": "Автор сценариев",
            "password": test_password,
            "roles": ["scenario_author"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ROLE_NOT_AVAILABLE"


async def test_short_password_is_rejected(security_client: AsyncClient) -> None:
    response = await security_client.post(
        "/api/v1/users",
        json={
            "username": "operator-8",
            "display_name": "Оператор Краткий",
            "password": "короткий",
            "roles": ["trainee"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "WEAK_PASSWORD"


async def test_revoking_a_role_immediately_ends_issued_sessions(
    app: FastAPI, security_client: AsyncClient, accounts: dict[str, str], test_password: str
) -> None:
    """Иначе снятая роль действовала бы до истечения токена."""

    expert = await login_as(app, "expert-1", test_password)
    try:
        assert (await expert.get("/api/v1/scenarios")).status_code == 200

        revoked = await security_client.delete(f"/api/v1/users/{accounts['expert-1']}/roles/expert")
        assert revoked.status_code == 200

        assert (await expert.get("/api/v1/scenarios")).status_code == 401
    finally:
        await expert.aclose()


async def test_deactivated_account_loses_access_at_once(
    app: FastAPI, security_client: AsyncClient, accounts: dict[str, str], test_password: str
) -> None:
    expert = await login_as(app, "expert-1", test_password)
    try:
        deactivated = await security_client.post(
            f"/api/v1/users/{accounts['expert-1']}/active", json={"is_active": False}
        )
        assert deactivated.status_code == 200

        assert (await expert.get("/api/v1/scenarios")).status_code == 401

        again = await security_client.post(
            "/api/v1/auth/login", json={"username": "expert-1", "password": test_password}
        )
        assert again.status_code == 401
    finally:
        await expert.aclose()


async def test_role_matrix_shows_the_next_cycle_as_not_assignable(expert_client: AsyncClient) -> None:
    roles = {item["role"]: item for item in (await expert_client.get("/api/v1/roles")).json()}

    assert roles["scenario_author"]["assignable"] is False
    assert roles["trainee"]["assignable"] is True
    # Требование: автор сценариев не получает системных прав вместе с правом на сценарии.
    author = set(roles["scenario_author"]["permissions"])
    assert not author & {"safety_rules.edit", "scoring.edit", "risk_model.edit", "results.delete"}


# --- список прохождений ------------------------------------------------


async def test_trainee_sees_only_sessions_assigned_to_them(
    instructor_client: AsyncClient, trainee_client: AsyncClient, configuration: SeededConfiguration
) -> None:
    await create_session(instructor_client, configuration, operator_id="operator-2")
    await create_session(instructor_client, configuration, operator_id="operator-1")

    mine = (await trainee_client.get("/api/v1/sessions")).json()

    assert [item["operator_id"] for item in mine] == ["operator-2"]


async def test_trainee_cannot_list_sessions_of_another_operator(trainee_client: AsyncClient) -> None:
    """Подстановка чужого фильтра — отказ, а не молчаливая подмена на свой."""

    response = await trainee_client.get("/api/v1/sessions?operator_id=operator-1")

    assert response.status_code == 403


async def test_instructor_sees_every_session(
    instructor_client: AsyncClient, configuration: SeededConfiguration
) -> None:
    await create_session(instructor_client, configuration, operator_id="operator-2")
    await create_session(instructor_client, configuration, operator_id="operator-1")

    everything = (await instructor_client.get("/api/v1/sessions")).json()

    assert {item["operator_id"] for item in everything} == {"operator-1", "operator-2"}


# --- самостоятельное прохождение без входа -----------------------------


async def start_guest(app: FastAPI) -> tuple[AsyncClient, dict[str, Any]]:
    """Клиент обучаемого, который сел за пульт без учётной записи."""

    http_client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    response = await http_client.post("/api/v1/auth/guest")
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    http_client.headers["authorization"] = f"Bearer {body['access_token']}"
    return http_client, body["user"]


async def test_guest_passes_the_whole_training_on_its_own(
    app: FastAPI, configuration: SeededConfiguration
) -> None:
    """Инструктора у самостоятельного обучаемого нет, поэтому ход он ведёт сам."""

    guest, user = await start_guest(app)
    try:
        assert user["roles"] == ["guest"]
        assert user["username"].startswith("guest-")

        session = await create_session(guest, configuration, operator_id=user["username"])
        started = await guest.post(
            f"/api/v1/sessions/{session['id']}/start", json={"request_id": str(uuid4())}
        )

        assert started.status_code == 200, started.text
        assert started.json()["status"] == "running"

        # Работа за пультом — то же право, что и у обучаемого с учётной записью.
        action = await guest.post(
            f"/api/v1/sessions/{session['id']}/observations",
            json={
                "request_id": str(uuid4()),
                "observation_type": "inspect_equipment",
                "target_code": "FEED-SYSTEM",
            },
        )
        assert action.status_code == 201, action.text
    finally:
        await guest.aclose()


async def test_guest_cannot_assign_training_to_someone_else(
    app: FastAPI, configuration: SeededConfiguration, accounts: dict[str, str]
) -> None:
    """Иначе чужие результаты обучения оказались бы подписаны кем угодно."""

    guest, _ = await start_guest(app)
    try:
        response = await guest.post(
            "/api/v1/sessions",
            json={
                "request_id": str(uuid4()),
                "operator_id": "operator-1",
                "scenario_version_id": configuration.scenario_version_id,
                "level_no": 1,
            },
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"
    finally:
        await guest.aclose()


async def test_guest_cannot_run_a_foreign_session(
    app: FastAPI, instructor_client: AsyncClient, configuration: SeededConfiguration
) -> None:
    """Право вести ход у гостя есть, но только над собственным прохождением."""

    foreign = await create_session(instructor_client, configuration, operator_id="operator-1")

    guest, _ = await start_guest(app)
    try:
        response = await guest.post(
            f"/api/v1/sessions/{foreign['id']}/start", json={"request_id": str(uuid4())}
        )

        assert response.status_code == 403
        assert response.json()["error"]["details"]["required_any_of"] == ["session.control"]
    finally:
        await guest.aclose()


async def test_guest_sees_neither_foreign_sessions_nor_closed_sections(
    app: FastAPI, instructor_client: AsyncClient, configuration: SeededConfiguration
) -> None:
    """Пульт открыт без входа, но открывается только пульт."""

    await create_session(instructor_client, configuration, operator_id="operator-1")

    guest, _ = await start_guest(app)
    try:
        assert (await guest.get("/api/v1/sessions")).json() == []
        assert (await guest.get("/api/v1/users")).status_code == 403
        assert (await guest.get("/api/v1/security-events")).status_code == 403
    finally:
        await guest.aclose()


async def test_guest_account_cannot_be_created_by_administrator(
    security_client: AsyncClient, test_password: str
) -> None:
    """Гостевую роль выдаёт только сервер вместе с токеном."""

    response = await security_client.post(
        "/api/v1/users",
        json={
            "username": "fake-guest",
            "display_name": "Подставной гость",
            "password": test_password,
            "roles": ["guest"],
        },
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "ROLE_NOT_AVAILABLE"
    assert error["details"]["roles"] == ["guest"]


async def test_guest_session_is_recorded_in_the_security_journal(
    app: FastAPI, security_client: AsyncClient
) -> None:
    """Вход без проверки личности отличается в журнале от проверенного входа."""

    guest, user = await start_guest(app)
    await guest.aclose()

    events = (await security_client.get("/api/v1/security-events?event_type=guest_session")).json()

    assert [item["actor_username"] for item in events] == [user["username"]]
