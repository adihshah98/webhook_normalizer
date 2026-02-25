import json
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.dlq import write_to_dlq
from app.db.models import Base, DLQEntry


@pytest.fixture
async def dlq_factory(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/test.db",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    # Patch the module-level async_session used by write_to_dlq
    import app.core.dlq as dlq_mod
    monkeypatch.setattr(dlq_mod, "async_session", factory)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_write_to_dlq(dlq_factory):
    await write_to_dlq({"a": 1}, "invalid payload", "req-123")

    async with dlq_factory() as session:
        result = await session.execute(select(DLQEntry))
        rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].request_id == "req-123"
    assert rows[0].reason == "invalid payload"
    assert rows[0].payload == {"a": 1}
