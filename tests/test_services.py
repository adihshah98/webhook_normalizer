import json
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.db.models import Base
from app.services.webhook_service import ingest
from app.utils.event_id import derive_event_id
from app.utils.validation import validate_webhook_body
from tests.conftest import make_adyen_signed_payload, make_stripe_signature

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


def test_derive_event_id_deterministic():
    body = {"a": 1, "b": 2}
    assert derive_event_id("unknown", body) == derive_event_id("unknown", body)


def test_derive_event_id_provider_keys():
    assert derive_event_id("stripe", {"id": "evt_1NG8Du2eZvKYlo2C"}) == "stripe:evt_1NG8Du2eZvKYlo2C"
    assert derive_event_id("paypal", {"id": "8PT597110X687430LKGECATA"}) == "paypal:8PT597110X687430LKGECATA"
    assert derive_event_id(
        "adyen",
        {
            "notificationItems": [
                {"NotificationRequestItem": {"eventCode": "AUTHORISATION", "pspReference": "8835761234567890"}}
            ]
        },
    ) == "adyen:AUTHORISATION:8835761234567890"
    # unknown fallback is hash
    key = derive_event_id("unknown", {"a": 1})
    assert key is not None
    assert len(key) <= 64
    assert key == derive_event_id("unknown", {"a": 1})


def test_validate_webhook_body_valid():
    assert validate_webhook_body({"x": 1}) is None


def test_validate_webhook_body_empty():
    assert validate_webhook_body({}) == "payload must be non-empty"


def test_validate_webhook_body_not_dict():
    assert validate_webhook_body([]) == "payload must be object"


@pytest.mark.asyncio
async def test_ingest_created(db_session: AsyncSession, stripe_webhook_secret: str):
    raw = json.dumps(STRIPE_PAYLOAD).encode()
    body, status = await ingest(
        db_session,
        raw,
        "req-1",
        headers={"Stripe-Signature": make_stripe_signature(raw, stripe_webhook_secret)},
    )
    assert status == 201
    assert body.event_id
    assert body.status == "created"


@pytest.mark.asyncio
async def test_ingest_returns_standardized(db_session: AsyncSession, stripe_webhook_secret: str):
    raw = json.dumps(STRIPE_PAYLOAD).encode()
    body, _ = await ingest(
        db_session,
        raw,
        "req-1",
        headers={"Stripe-Signature": make_stripe_signature(raw, stripe_webhook_secret)},
    )
    assert body.standardized
    std = body.standardized
    assert set(std.keys()) == {"event_id", "source", "extracted", "raw"}
    assert std["source"] == "stripe"
    assert std["extracted"]["customer_id"] == "cus_xyz789"


@pytest.mark.asyncio
async def test_ingest_duplicate(db_session: AsyncSession, stripe_webhook_secret: str):
    raw = json.dumps(STRIPE_PAYLOAD).encode()
    sig = make_stripe_signature(raw, stripe_webhook_secret)
    h = {"Stripe-Signature": sig}
    r1, s1 = await ingest(db_session, raw, "r1", headers=h)
    r2, s2 = await ingest(db_session, raw, "r2", headers=h)
    assert s1 == 201
    assert s2 == 200
    assert r1.event_id == r2.event_id


@pytest.mark.asyncio
async def test_ingest_invalid_empty(db_session: AsyncSession):
    body, status = await ingest(db_session, json.dumps({}).encode(), "req-1")
    assert status == 202
    assert body.status == "invalid"
    assert body.dlq is True


@pytest.mark.asyncio
async def test_ingest_invalid_bad_json(db_session: AsyncSession):
    body, status = await ingest(db_session, b"not json", "req-1")
    assert status == 202
    assert body.status == "invalid"


@pytest.mark.asyncio
async def test_ingest_stripe_signature_invalid(db_session: AsyncSession, monkeypatch):
    """Stripe event with invalid signature returns 401 when secret is configured."""
    monkeypatch.setattr(
        "app.services.webhook_service._settings",
        type(
            "Settings",
            (),
            {"stripe_webhook_secret": "whsec_test123", "adyen_hmac_key": None, "paypal_webhook_id": None},
        )(),
    )
    raw = json.dumps(STRIPE_PAYLOAD).encode()
    body, status = await ingest(
        db_session, raw, "req-1", headers={"Stripe-Signature": "t=1,v1=invalid"}
    )
    assert status == 401
    assert body.status == "invalid"
    assert body.reason == "invalid signature"


# --- Adyen ---


@pytest.mark.asyncio
async def test_ingest_adyen_created(db_session: AsyncSession, adyen_hmac_key: str):
    payload = make_adyen_signed_payload(adyen_hmac_key)
    raw = json.dumps(payload).encode()
    body, status = await ingest(db_session, raw, "req-adyen")
    assert status == 201
    assert body.event_id
    assert body.status == "created"


@pytest.mark.asyncio
async def test_ingest_adyen_returns_standardized(db_session: AsyncSession, adyen_hmac_key: str):
    payload = make_adyen_signed_payload(adyen_hmac_key)
    raw = json.dumps(payload).encode()
    body, _ = await ingest(db_session, raw, "req-adyen")
    assert body.standardized
    std = body.standardized
    assert set(std.keys()) == {"event_id", "source", "extracted", "raw"}
    assert std["source"] == "adyen"
    e = std["extracted"]
    assert e["provider_event_id"] == "7914073381342284"
    assert e["event_type"] == "AUTHORISATION"
    assert e["merchant_account"] == "TestMerchant"
    assert e["amount"] == {"value": 1130, "currency": "EUR"}


@pytest.mark.asyncio
async def test_ingest_adyen_duplicate(db_session: AsyncSession, adyen_hmac_key: str):
    payload = make_adyen_signed_payload(adyen_hmac_key)
    raw = json.dumps(payload).encode()
    r1, s1 = await ingest(db_session, raw, "r1")
    r2, s2 = await ingest(db_session, raw, "r2")
    assert s1 == 201
    assert s2 == 200
    assert r1.event_id == r2.event_id


@pytest.mark.asyncio
async def test_ingest_adyen_signature_invalid(db_session: AsyncSession, monkeypatch):
    """Adyen notification with invalid HMAC returns 401 when key is configured."""
    monkeypatch.setattr(
        "app.services.webhook_service._settings",
        type(
            "Settings",
            (),
            {"stripe_webhook_secret": None, "adyen_hmac_key": "00" * 32, "paypal_webhook_id": None},
        )(),
    )
    payload = make_adyen_signed_payload("44782DEF547AAA06C910C43932B1EB0C71FC68D9D0C057550C48EC2ACF6BA056")
    raw = json.dumps(payload).encode()
    body, status = await ingest(db_session, raw, "req-adyen")
    assert status == 401
    assert body.status == "invalid"
    assert body.reason == "invalid signature"


@pytest.mark.asyncio
async def test_ingest_paypal_signature_invalid(db_session: AsyncSession, monkeypatch):
    """PayPal webhook with invalid/missing signature headers returns 401 when webhook_id is configured."""
    monkeypatch.setattr(
        "app.services.webhook_service._settings",
        type(
            "Settings",
            (),
            {
                "stripe_webhook_secret": None,
                "adyen_hmac_key": None,
                "paypal_webhook_id": "WH-SUB-123",
                "notification_webhook_url": None,
            },
        )(),
    )
    payload = {
        "id": "WH-evt-123",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "create_time": "2024-05-16T05:19:19Z",
        "resource": {"id": "cap-1", "status": "COMPLETED", "amount": {"value": "10.00", "currency_code": "USD"}},
    }
    raw = json.dumps(payload).encode()
    # Pass paypal-transmission-id so we attempt verification; other headers missing → verification fails → 401
    headers = {"paypal-transmission-id": "t-123"}
    body, status = await ingest(db_session, raw, "req-paypal", headers=headers)
    assert status == 401
    assert body.reason == "invalid signature"
