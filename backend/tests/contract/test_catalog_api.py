import pytest
from httpx import AsyncClient

from app.application.configuration import publish_installation, publish_scenario, publish_scoring_policy
from app.infrastructure.db.engine import Database
from app.infrastructure.seed.installation import build_installation_spec


@pytest.fixture
async def seeded(database: Database) -> None:
    async with database.session_factory() as session, session.begin():
        installation = await publish_installation(session, build_installation_spec())
        await publish_scenario(session, installation)
        await publish_scoring_policy(session)


async def test_scenarios_list_returns_published_version(client: AsyncClient, seeded: None) -> None:
    response = await client.get("/api/v1/scenarios")

    assert response.status_code == 200
    scenarios = response.json()
    assert len(scenarios) == 1
    assert scenarios[0]["scenario_code"] == "ELOU-AVT-FULL-RUN"
    assert scenarios[0]["duration_ms"] == 3_900_000


async def test_scenario_detail_exposes_levels_and_stages(client: AsyncClient, seeded: None) -> None:
    scenario_id = (await client.get("/api/v1/scenarios")).json()[0]["id"]

    response = await client.get(f"/api/v1/scenarios/{scenario_id}")

    assert response.status_code == 200
    scenario = response.json()
    assert [level["level_no"] for level in scenario["levels"]] == [1, 2, 3]
    assert scenario["stages"][0]["code"] == "precheck"
    assert scenario["stages"][-1]["code"] == "final_stabilization"


async def test_scenario_detail_hides_disturbance_and_reference_actions(
    client: AsyncClient, seeded: None
) -> None:
    """Скрытая причина, момент возмущения и эталон действий не покидают backend."""

    scenario_id = (await client.get("/api/v1/scenarios")).json()[0]["id"]

    response = await client.get(f"/api/v1/scenarios/{scenario_id}")

    assert set(response.json()) == {
        "id",
        "scenario_code",
        "version",
        "name",
        "description",
        "duration_ms",
        "installation_version_id",
        "levels",
        "stages",
    }
    for leaked in (
        "hidden",
        "pump_capacity_loss",
        "valve_stiction",
        "earliest_sim_time_ms",
        "target_branch_flow_loss",
        "target_selector",
    ):
        assert leaked not in response.text


async def test_unknown_scenario_returns_stable_error_code(client: AsyncClient, seeded: None) -> None:
    response = await client.get("/api/v1/scenarios/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SCENARIO_NOT_FOUND"


async def test_topology_returns_equipment_tags_and_edges(client: AsyncClient, seeded: None) -> None:
    scenario = (await client.get("/api/v1/scenarios")).json()[0]

    response = await client.get(f"/api/v1/installations/{scenario['installation_version_id']}/topology")

    assert response.status_code == 200
    topology = response.json()
    codes = {item["code"] for item in topology["equipment"]}
    assert {"FRC-404", "FRC-405", "FRC-406", "ELOU", "K-1", "K-2"} <= codes

    branch_edges = [edge for edge in topology["edges"] if edge["branch_no"] == 2]
    assert branch_edges, "вторая сырьевая ветвь должна быть представлена в топологии"

    controller = next(item for item in topology["equipment"] if item["code"] == "FRC-405")
    flow_tag = next(tag for tag in controller["tags"] if tag["code"] == "branch_2_flow_tph")
    assert flow_tag["unit"] == "t/h"
    assert flow_tag["critical_min"] == 88.0


async def test_equipment_reports_its_parent_section(client: AsyncClient, seeded: None) -> None:
    scenario = (await client.get("/api/v1/scenarios")).json()[0]

    topology = (
        await client.get(f"/api/v1/installations/{scenario['installation_version_id']}/topology")
    ).json()

    exchanger = next(item for item in topology["equipment"] if item["code"] == "T-4/1")
    assert exchanger["parent_code"] == "T-1_T-11"
