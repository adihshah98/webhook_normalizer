import json
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.db.models import Base
from app.services.webhook_service import ingest
from app.utils.event_id import derive_event_id
from app.utils.validation import validate_webhook_body

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


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/test.db", echo=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_derive_event_id_deterministic():
    body = {"a": 1, "b": 2}
    assert derive_event_id(body, None) == derive_event_id(body, None)


@pytest.mark.asyncio
async def test_derive_event_id_idempotency_key():
    assert derive_event_id({"a": 1}, "my-key-123") == "my-key-123"


def test_validate_webhook_body_valid():
    assert validate_webhook_body({"x": 1}) is None


def test_validate_webhook_body_empty():
    assert validate_webhook_body({}) == "payload must be non-empty"


def test_validate_webhook_body_not_dict():
    assert validate_webhook_body([]) == "payload must be object"


@pytest.mark.asyncio
async def test_ingest_created(db_session: AsyncSession):
    body, status = await ingest(
        db_session,
        json.dumps(CRM_PAYLOAD).encode(),
        None,
        "req-1",
    )
    assert status == 201
    assert body.event_id
    assert body.status == "created"


@pytest.mark.asyncio
async def test_ingest_returns_standardized(db_session: AsyncSession):
    body, _ = await ingest(
        db_session, json.dumps(CRM_PAYLOAD).encode(), None, "req-1"
    )
    assert body.standardized
    std = body.standardized
    assert std["source"] == "crm"
    assert std["customer_id"] == "acct_789"


@pytest.mark.asyncio
async def test_ingest_duplicate(db_session: AsyncSession):
    r1, s1 = await ingest(db_session, json.dumps(CRM_PAYLOAD).encode(), None, "r1")
    r2, s2 = await ingest(db_session, json.dumps(CRM_PAYLOAD).encode(), None, "r2")
    assert s1 == 201
    assert s2 == 200
    assert r1.event_id == r2.event_id


@pytest.mark.asyncio
async def test_ingest_invalid_empty(db_session: AsyncSession):
    body, status = await ingest(db_session, json.dumps({}).encode(), None, "req-1")
    assert status == 202
    assert body.status == "invalid"
    assert body.dlq is True


@pytest.mark.asyncio
async def test_ingest_invalid_bad_json(db_session: AsyncSession):
    body, status = await ingest(db_session, b"not json", None, "req-1")
    assert status == 202
    assert body.status == "invalid"
