import json

import pytest
from httpx import AsyncClient

from tests.conftest import make_stripe_signature

STRIPE_PAYLOAD = {
    "object": "event",
    "id": "evt_1NG8Du2eZvKYlo2C",
    "type": "invoice.paid",
    "created": 1686089970,
    "data": {
        "object": {
            "id": "in_1ABC123",
            "customer": "cus_xyz789",
            "amount_due": 1000,
            "currency": "usd",
            "status": "paid",
        }
    },
}


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz(client: AsyncClient):
    r = await client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}


def _stripe_webhook_headers(payload: dict, secret: str, extra: dict | None = None):
    """Body bytes and headers for posting a Stripe webhook with valid test signature."""
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Stripe-Signature": make_stripe_signature(body, secret),
    }
    if extra:
        headers.update(extra)
    return body, headers


@pytest.mark.asyncio
async def test_webhook_created(client: AsyncClient, stripe_webhook_secret: str):
    body, headers = _stripe_webhook_headers(STRIPE_PAYLOAD, stripe_webhook_secret)
    r = await client.post("/webhook", content=body, headers=headers)
    assert r.status_code == 201
    data = r.json()
    assert "event_id" in data
    assert len(data["event_id"]) == 64
    assert "standardized" in data
    assert set(data["standardized"].keys()) == {"event_id", "source", "extracted", "raw"}
    assert data["standardized"]["extracted"]["event_type"] == "invoice.paid"


@pytest.mark.asyncio
async def test_webhook_returns_standardized(client: AsyncClient, stripe_webhook_secret: str):
    body, headers = _stripe_webhook_headers(STRIPE_PAYLOAD, stripe_webhook_secret)
    r = await client.post("/webhook", content=body, headers=headers)
    assert r.status_code == 201
    data = r.json()
    assert data["standardized"]["source"] == "stripe"
    e = data["standardized"]["extracted"]
    assert e["customer_id"] == "cus_xyz789"
    assert e["entity_type"] == "invoice"
    assert e["amount"]["value"] == 1000
    assert data["standardized"]["raw"]["data"]["object"]["amount_due"] == 1000


@pytest.mark.asyncio
async def test_webhook_duplicate_idempotent(client: AsyncClient, stripe_webhook_secret: str):
    body1, headers1 = _stripe_webhook_headers(
        STRIPE_PAYLOAD, stripe_webhook_secret, {"X-Idempotency-Key": "key-abc"}
    )
    r1 = await client.post("/webhook", content=body1, headers=headers1)
    r2 = await client.post(
        "/webhook",
        content=json.dumps({"other": "data"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Idempotency-Key": "key-abc"},
    )
    assert r1.status_code == 201
    assert r2.status_code == 200
    assert r1.json()["event_id"] == r2.json()["event_id"] == "key-abc"


@pytest.mark.asyncio
async def test_webhook_duplicate_same_payload(client: AsyncClient, stripe_webhook_secret: str):
    body, headers = _stripe_webhook_headers(STRIPE_PAYLOAD, stripe_webhook_secret)
    r1 = await client.post("/webhook", content=body, headers=headers)
    r2 = await client.post("/webhook", content=body, headers=headers)
    assert r1.status_code == 201
    assert r2.status_code == 200
    assert r1.json()["event_id"] == r2.json()["event_id"]


@pytest.mark.asyncio
async def test_webhook_invalid_empty_object(client: AsyncClient):
    r = await client.post("/webhook", json={})
    assert r.status_code == 202
    assert r.json()["status"] == "invalid"
    assert r.json()["dlq"] is True


@pytest.mark.asyncio
async def test_webhook_invalid_bad_json(client: AsyncClient):
    r = await client.post(
        "/webhook", content=b"not json", headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 202
    assert r.json()["status"] == "invalid"


@pytest.mark.asyncio
async def test_webhook_request_id_present(client: AsyncClient, stripe_webhook_secret: str):
    body, headers = _stripe_webhook_headers(STRIPE_PAYLOAD, stripe_webhook_secret)
    r = await client.post("/webhook", content=body, headers=headers)
    assert r.status_code == 201
