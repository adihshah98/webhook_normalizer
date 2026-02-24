import hmac
import hashlib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.core.deps import get_session
from app.db.models import Base

# Fake secret for tests only. Never use a real Stripe webhook secret in tests or CI.
TEST_WEBHOOK_SECRET = "whsec_test_secret_123"


def make_stripe_signature(payload: bytes, secret: str, timestamp: str = "1234567890") -> str:
    """Build a valid Stripe-Signature header using Stripe's algorithm (HMAC-SHA256)."""
    signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
    signature = hmac.new(
        secret.encode(),
        signed_payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


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
                "notification_webhook_url": None,
            },
        )(),
    )


@pytest.fixture
def stripe_webhook_secret():
    """Fake Stripe webhook secret for signing requests in tests. Matches use_test_webhook_secret."""
    return TEST_WEBHOOK_SECRET


@pytest.fixture
async def client(tmp_path: Path):
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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await test_engine.dispose()
