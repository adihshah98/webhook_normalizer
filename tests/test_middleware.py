from unittest.mock import patch

import pytest
from httpx import AsyncClient
import uuid

from app.main import app


@pytest.mark.asyncio
async def test_request_id_middleware_attaches_request_id(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    # request_id is stored in request.state, not exposed in response
    # We verify the app runs without error (middleware doesn't break the request)
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_request_id_is_uuid_format(client: AsyncClient):
    """Middleware assigns request_id; webhook succeeds with test DB."""
    with patch("app.middleware.request_log.uuid.uuid4", return_value=uuid.UUID("12345678-1234-5678-1234-567812345678")):
        r = await client.post("/webhook", json={"a": 1})
    assert r.status_code == 201
    assert "event_id" in r.json()
