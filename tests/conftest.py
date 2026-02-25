import base64
import binascii
import hmac
import hashlib
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.core.deps import get_session
from app.db.models import Base

# Fake secret for tests only
TEST_WEBHOOK_SECRET = "whsec_test_secret_123"
# Fake Adyen HMAC key (hex) for tests only.
TEST_ADYEN_HMAC_KEY = "44782DEF547AAA06C910C43932B1EB0C71FC68D9D0C057550C48EC2ACF6BA056"


def make_stripe_signature(payload: bytes, secret: str, timestamp: str | None = None) -> str:
    """Build a valid Stripe-Signature header using Stripe's algorithm (HMAC-SHA256)."""
    if timestamp is None:
        timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
    signature = hmac.new(
        secret.encode(),
        signed_payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


def _adyen_signing_string(item: dict) -> str:
    """Build the colon-delimited string used for Adyen HMAC (without additionalData)."""
    request_dict = dict(item)
    request_dict.pop("additionalData", None)
    amount = request_dict.get("amount")
    if isinstance(amount, dict):
        request_dict["value"] = amount.get("value", "")
        request_dict["currency"] = amount.get("currency", "")
    else:
        request_dict["value"] = ""
        request_dict["currency"] = ""
    element_orders = [
        "pspReference",
        "originalReference",
        "merchantAccountCode",
        "merchantReference",
        "value",
        "currency",
        "eventCode",
        "success",
    ]
    return ":".join(str(request_dict.get(el, "")) for el in element_orders)


def make_adyen_signed_payload(
    hmac_key_hex: str,
    item: dict | None = None,
) -> dict:
    """Build an Adyen Standard webhook body with one signed NotificationRequestItem."""
    if item is None:
        item = {
            "amount": {"value": 1130, "currency": "EUR"},
            "pspReference": "7914073381342284",
            "eventCode": "AUTHORISATION",
            "eventDate": "2019-05-06T17:15:34.121+02:00",
            "merchantAccountCode": "TestMerchant",
            "merchantReference": "TestPayment-1407325143704",
            "paymentMethod": "visa",
            "success": "true",
        }
    item = dict(item)
    key_bytes = binascii.a2b_hex(hmac_key_hex.strip())
    signing_string = _adyen_signing_string(item)
    sig = base64.b64encode(
        hmac.new(key_bytes, signing_string.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")
    item.setdefault("additionalData", {})["hmacSignature"] = sig
    return {
        "live": "false",
        "notificationItems": [{"NotificationRequestItem": item}],
    }


@pytest.fixture(autouse=True)
def use_test_webhook_secret(monkeypatch):
    """Use a fake webhook secret in tests so verification runs without touching .env.
    test_ingest_stripe_signature_invalid overrides this to test invalid-signature rejection."""
    from app.services import webhook_service

    monkeypatch.setattr(
        webhook_service,
        "_settings",
        type(
            "Settings",
            (),
            {
                "stripe_webhook_secret": TEST_WEBHOOK_SECRET,
                "adyen_hmac_key": TEST_ADYEN_HMAC_KEY,
                "paypal_webhook_id": None,
                "notification_webhook_url": None,
            },
        )(),
    )


@pytest.fixture
def stripe_webhook_secret():
    """Fake Stripe webhook secret for signing requests in tests. Matches use_test_webhook_secret."""
    return TEST_WEBHOOK_SECRET


@pytest.fixture
def adyen_hmac_key():
    """Fake Adyen HMAC key for signing requests in tests."""
    return TEST_ADYEN_HMAC_KEY


@pytest.fixture
async def client(tmp_path: Path, monkeypatch):
    """Test client with isolated DB (events + dlq tables)."""
    db_path = tmp_path / "test.db"

    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
    )
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_session():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    # Patch DLQ's async_session so it uses the test DB
    import app.core.dlq as dlq_mod
    monkeypatch.setattr(dlq_mod, "async_session", test_session_factory)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await test_engine.dispose()
