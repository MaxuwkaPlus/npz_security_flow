from httpx import AsyncClient


async def test_health_reports_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_checks_database_connection(client: AsyncClient) -> None:
    response = await client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_unknown_route_uses_unified_error_format(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "HTTP_ERROR"
    assert error["request_id"] == response.headers["X-Request-ID"]
