import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.db.models import Base, Event
from app.db.events import insert_event


@pytest.fixture
async def session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/db.db", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await engine.dispose()


@pytest.mark.asyncio
async def test_insert_event_created(session: AsyncSession):
    result = await insert_event(session, "ev-1", '{"a":1}')
    assert result == "created"
    row = (await session.execute(select(Event).where(Event.event_id == "ev-1"))).scalar_one()
    assert row.payload == '{"a":1}'


@pytest.mark.asyncio
async def test_insert_event_duplicate(session: AsyncSession):
    r1 = await insert_event(session, "ev-dup", '{"x":1}')
    r2 = await insert_event(session, "ev-dup", '{"x":2}')
    assert r1 == "created"
    assert r2 == "duplicate"
