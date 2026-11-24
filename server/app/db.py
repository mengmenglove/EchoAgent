"""数据库连接：一个全局 engine + session 工厂。

支持两种数据库：
- SQLite 文件：本地开发，零安装
- Postgres：上线用
"""

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event, make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings


def _engine_kwargs(url: str) -> dict:
    u = make_url(url)
    if u.get_backend_name() != "sqlite":
        return {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 10}
    if u.database in (None, "", ":memory:"):
        # 内存库：每个新连接都是一个空库，所以所有会话必须共用一个连接
        return {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
    # 文件库：每个会话用自己的连接（共用连接会让不同会话的事务混在一起）。
    # SQLite 同一时刻只能有一个写事务，timeout 是等待别人写完的最长秒数
    return {"connect_args": {"timeout": 30}}


engine = create_async_engine(settings.database_url, **_engine_kwargs(settings.database_url))

if engine.dialect.name == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")  # SQLite 默认不执行外键约束（包括 ON DELETE CASCADE）
        dbapi_conn.execute("PRAGMA journal_mode=WAL")  # 读写互不阻塞：Worker 写进度时，接口照样能读


# expire_on_commit=False：commit 后对象属性仍可直接访问，异步模式下必须这样设
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个会话，请求结束自动关闭。"""
    async with SessionLocal() as session:
        yield session


async def get_for_update[T](db: AsyncSession, model: type[T], pk: Any, *, key_share: bool = False) -> T | None:
    """加锁读取一行，保证"读出来 → 改 → 写回去"期间没有别人插进来。锁在 commit / rollback 时释放。

    SQLite 没有行锁，SELECT ... FOR UPDATE 会被忽略。这里用一条不改任何数据的 UPDATE
    先拿到整个库的写锁，效果相同，只是粒度更粗。
    populate_existing 保证拿到的是加锁后的最新值，而不是会话里缓存的旧值。
    """
    if engine.dialect.name == "sqlite":
        await db.execute(text("UPDATE users SET id = id WHERE 1 = 0"))
    lock: Any = {"key_share": True} if key_share else True
    return await db.get(model, pk, with_for_update=lock, populate_existing=True)
