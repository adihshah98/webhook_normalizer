import pytest
from httpx import AsyncClient

CRM_PAYLOAD = {
    "event_type": "contact.created",
    "event_id": "00X8a00000123Ab",
    "occurred_at": "2024-01-01T12:34:56Z",
    "account": {"id": "acct_789", "name": "Acme Corp"},
    "contact": {
        "id": "0038a00000456Cd",
        "email": "alice@acme.com",
        "first_name": "Alice",
        "last_name": "Smith",
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


@pytest.mark.asyncio
async def test_webhook_created(client: AsyncClient):
    r = await client.post("/webhook", json=CRM_PAYLOAD)
    assert r.status_code == 201
    data = r.json()
    assert "event_id" in data
    assert len(data["event_id"]) == 64
    assert "standardized" in data
    assert data["standardized"]["event_type"] == "contact.created"


@pytest.mark.asyncio
async def test_webhook_returns_standardized(client: AsyncClient):
    r = await client.post("/webhook", json=CRM_PAYLOAD)
    assert r.status_code == 201
    data = r.json()
    assert data["standardized"]["source"] == "crm"
    assert data["standardized"]["customer_id"] == "acct_789"
    assert data["standardized"]["entity_type"] == "contact"
    assert data["standardized"]["payload"]["email"] == "alice@acme.com"


@pytest.mark.asyncio
async def test_webhook_duplicate_idempotent(client: AsyncClient):
    r1 = await client.post(
        "/webhook", json=CRM_PAYLOAD, headers={"X-Idempotency-Key": "key-abc"}
    )
    r2 = await client.post(
        "/webhook", json={"other": "data"}, headers={"X-Idempotency-Key": "key-abc"}
    )
    assert r1.status_code == 201
    assert r2.status_code == 200
    assert r1.json()["event_id"] == r2.json()["event_id"] == "key-abc"


@pytest.mark.asyncio
async def test_webhook_duplicate_same_payload(client: AsyncClient):
    r1 = await client.post("/webhook", json=CRM_PAYLOAD)
    r2 = await client.post("/webhook", json=CRM_PAYLOAD)
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
async def test_webhook_request_id_present(client: AsyncClient):
    r = await client.post("/webhook", json=CRM_PAYLOAD)
    assert r.status_code == 201
