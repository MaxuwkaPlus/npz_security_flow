"""Контракт OpenAPI: состав API и отсутствие скрытых полей в схемах ответов."""

import json
from typing import Any

from fastapi import FastAPI

# Точные имена полей: `suspected_cause_code` — это заявление оператора, а не разгадка.
HIDDEN_FIELDS = frozenset(
    {
        "hidden_runtime_config_json",
        "runtime_state_json",
        "severity",
        "onset_delay_ms",
        "is_correct",
        "cause_code",
        "target_branch",
    }
)
EXPECTED_PATHS = {
    "/api/v1/health",
    "/api/v1/ready",
    "/api/v1/scenarios",
    "/api/v1/scenarios/{scenario_version_id}",
    "/api/v1/installations/{installation_version_id}/topology",
    "/api/v1/sessions",
    "/api/v1/sessions/{session_id}",
    "/api/v1/sessions/{session_id}/state",
    "/api/v1/sessions/{session_id}/start",
    "/api/v1/sessions/{session_id}/pause",
    "/api/v1/sessions/{session_id}/resume",
    "/api/v1/sessions/{session_id}/abort",
    "/api/v1/sessions/{session_id}/actions",
    "/api/v1/sessions/{session_id}/actions/{action_id}/cancel",
    "/api/v1/sessions/{session_id}/observations",
    "/api/v1/sessions/{session_id}/diagnoses",
    "/api/v1/sessions/{session_id}/alarms",
    "/api/v1/sessions/{session_id}/alarms/{alarm_id}/acknowledge",
    "/api/v1/sessions/{session_id}/sagat/current",
    "/api/v1/sessions/{session_id}/sagat/{checkpoint_id}/answers",
    "/api/v1/sessions/{session_id}/nasa-tlx",
    "/api/v1/sessions/{session_id}/report",
    "/api/v1/operators/{operator_id}/level-comparison",
}


def schemas_of(app: FastAPI) -> dict[str, Any]:
    spec: dict[str, Any] = app.openapi()
    components: dict[str, Any] = spec.get("components", {}).get("schemas", {})
    return components


def test_every_documented_path_is_versioned(app: FastAPI) -> None:
    spec = app.openapi()

    assert set(spec["paths"]) == EXPECTED_PATHS
    assert all(path.startswith("/api/v1/") for path in spec["paths"])


def test_every_operation_belongs_to_exactly_one_documented_group(app: FastAPI) -> None:
    """Ручка без группы теряется на странице /docs, с двумя — показывается дважды."""

    spec = app.openapi()
    documented = {tag["name"] for tag in spec["tags"]}
    tags_by_operation = {
        f"{method.upper()} {path}": operation.get("tags", [])
        for path, item in spec["paths"].items()
        for method, operation in item.items()
    }

    assert all(len(tags) == 1 for tags in tags_by_operation.values()), tags_by_operation
    assert {tag for tags in tags_by_operation.values() for tag in tags} <= documented


def test_every_operation_is_described(app: FastAPI) -> None:
    """Заголовок читается в свёрнутом списке /docs, описание объясняет назначение ручки."""

    spec = app.openapi()
    undocumented = [
        f"{method.upper()} {path}"
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if not operation.get("summary") or not operation.get("description")
    ]

    assert undocumented == []


def test_no_response_schema_exposes_hidden_state(app: FastAPI) -> None:
    """Скрытая причина, интенсивность возмущения и правильность диагноза вне контракта."""

    exposed: set[str] = set()
    for name, schema in schemas_of(app).items():
        if name.endswith("Request"):
            continue
        exposed |= set(schema.get("properties", {}))

    assert exposed & HIDDEN_FIELDS == set()


def test_random_seed_is_only_an_instructor_input(app: FastAPI) -> None:
    """Seed задаёт инструктор для воспроизводимой демонстрации, но обратно не читает."""

    holders = [name for name, schema in schemas_of(app).items() if "random_seed" in json.dumps(schema)]

    assert holders == ["CreateSessionRequest"]


def test_error_responses_share_one_shape(app: FastAPI) -> None:
    spec = app.openapi()
    operations = [
        operation
        for path in spec["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict)
    ]

    # Валидация тела запроса описана единым способом во всех мутирующих операциях.
    with_validation = [operation for operation in operations if "422" in operation.get("responses", {})]
    assert with_validation
    assert all(
        operation["responses"]["422"]["description"] == "Validation Error" for operation in with_validation
    )
