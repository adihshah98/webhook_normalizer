import json
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import make_stripe_signature

# Stripe-shaped payload so request is processed (201); unknown payload would get 202
STRIPE_PAYLOAD = {
    "object": "event",
    "id": "evt_rate_limit_test",
    "type": "invoice.paid",
    "created": 1686089970,
    "data": {"object": {"id": "in_1", "customer": "cus_1"}},
}


@pytest.fixture
async def rate_limited_client(tmp_path):
    """Client with rate limit: 2 requests per 60s."""
    from app.core.rate_limit import InMemoryRateLimiter
    from app.db.models import Base
    from app.core.deps import get_session
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

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

    app.state.rate_limiter = InMemoryRateLimiter(
        requests_per_window=2,
        window_seconds=60.0,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_rate_limit_returns_429_when_exceeded(rate_limited_client, stripe_webhook_secret: str):
    body = json.dumps(STRIPE_PAYLOAD).encode()
    headers = {
        "Content-Type": "application/json",
        "Stripe-Signature": make_stripe_signature(body, stripe_webhook_secret),
    }
    r1 = await rate_limited_client.post("/webhook", content=body, headers=headers)
    r2 = await rate_limited_client.post("/webhook", content=body, headers=headers)
    r3 = await rate_limited_client.post("/webhook", content=body, headers=headers)

    assert r1.status_code in (200, 201)
    assert r2.status_code in (200, 201)
    assert r3.status_code == 429
    assert r3.json()["detail"] == "Too many requests"
    assert "Retry-After" in r3.headers
