import pytest
from unittest.mock import patch
from httpx import ASGITransport, AsyncClient

from app.main import app

CRM_PAYLOAD = {
    "event_type": "contact.created",
    "account": {"id": "acct_789"},
    "contact": {"id": "c1", "email": "a@b.com"},
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
async def test_rate_limit_returns_429_when_exceeded(rate_limited_client):
    r1 = await rate_limited_client.post("/webhook", json=CRM_PAYLOAD)
    r2 = await rate_limited_client.post("/webhook", json=CRM_PAYLOAD)
    r3 = await rate_limited_client.post("/webhook", json=CRM_PAYLOAD)

    assert r1.status_code in (200, 201)
    assert r2.status_code in (200, 201)
    assert r3.status_code == 429
    assert r3.json()["detail"] == "Too many requests"
    assert "Retry-After" in r3.headers
