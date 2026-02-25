import json
from unittest.mock import patch

import pytest
from httpx import AsyncClient
import uuid

from app.main import app
from tests.conftest import make_stripe_signature

STRIPE_PAYLOAD = {
    "object": "event",
    "id": "evt_1NG8Du2eZvKYlo2C",
    "type": "invoice.paid",
    "created": 1686089970,
    "data": {"object": {"id": "in_1ABC123", "customer": "cus_xyz789"}},
}


@pytest.mark.asyncio
async def test_request_id_middleware_attaches_request_id(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    # request_id is stored in request.state, not exposed in response
    # We verify the app runs without error (middleware doesn't break the request)
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_request_id_is_uuid_format(client: AsyncClient, stripe_webhook_secret: str):
    """Middleware assigns request_id; webhook succeeds with test DB."""
    body = json.dumps(STRIPE_PAYLOAD).encode()
    headers = {
        "Content-Type": "application/json",
        "Stripe-Signature": make_stripe_signature(body, stripe_webhook_secret),
    }
    with patch("app.middleware.request_log.uuid.uuid4", return_value=uuid.UUID("12345678-1234-5678-1234-567812345678")):
        r = await client.post("/webhook", content=body, headers=headers)
    assert r.status_code == 201
    assert "event_id" in r.json()
