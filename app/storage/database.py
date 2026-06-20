from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession, AsyncEngine
from contextlib import contextmanager
from config import settings

# ── Sync engine (for existing code: bot handlers, web server) ────────
_sync_url = settings.database_url_sync
_sync_kwargs = {}
if _sync_url.startswith("postgresql"):
    _sync_kwargs["pool_size"] = 5
    _sync_kwargs["max_overflow"] = 3
    _sync_kwargs["pool_pre_ping"] = True

sync_engine = create_engine(_sync_url, **_sync_kwargs)

SyncSession = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


@contextmanager
def db_session():
    session = SyncSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_sync_db():
    db = SyncSession()
    try:
        yield db
    finally:
        db.close()


# ── Async engine (for Playwright scraper, Celery tasks) ──────────────
_async_url = settings.database_url
_async_kwargs = {"echo": False}
if _async_url.startswith("postgresql"):
    _async_kwargs["pool_size"] = 5
    _async_kwargs["max_overflow"] = 3
    _async_kwargs["pool_pre_ping"] = True

async_engine: AsyncEngine = create_async_engine(_async_url, **_async_kwargs)

async_session = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


# ── Base & init ──────────────────────────────────────────────────────
Base = declarative_base()


def init_sync_db():
    Base.metadata.create_all(bind=sync_engine)


async def init_async_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_async_db():
    await async_engine.dispose()


# Backward compatibility aliases
SessionLocal = SyncSession
init_db = init_sync_db
