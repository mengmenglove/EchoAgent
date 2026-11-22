"""数据库连接：一个全局 engine + session 工厂。"""

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        # 测试用的内存 SQLite：所有连接共享同一个库
        return {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
    return {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 10}


engine = create_async_engine(settings.database_url, **_engine_kwargs(settings.database_url))

if settings.database_url.startswith("sqlite"):
    # SQLite 默认不执行外键约束（包括 ON DELETE CASCADE），测试环境要手动打开
    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")


# expire_on_commit=False：commit 后对象属性仍可直接访问，异步模式下必须这样设
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个会话，请求结束自动关闭。"""
    async with SessionLocal() as session:
        yield session
