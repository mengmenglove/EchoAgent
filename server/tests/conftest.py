"""测试夹具。

不依赖 Postgres / Redis / F5 / Claude：
- 数据库：临时文件 SQLite（模型里用了 with_variant，JSONB 自动退化成 JSON）；
  TEST_DATABASE_URL=postgresql+asyncpg://... 可以换成真实 Postgres
- Redis：fakeredis（支持 publish/subscribe、incr）
- 队列：FakeQueue，只记录入队了什么，由测试手动调用 pipeline.run 模拟 Worker
- TTS：MockProvider 生成提示音
- Claude：FakeLLM 按顺序返回预设的响应
"""

import os
import tempfile

_db_dir = tempfile.TemporaryDirectory(prefix="echo-testdb-")

# 必须在导入 app 之前设置，因为 app.config 在导入时就读取配置
os.environ.update(
    {
        # 默认用临时文件 SQLite（和本地开发一致，每个会话有自己的连接）；
        # 设置 TEST_DATABASE_URL 可以在真实 Postgres 上跑同一套测试
        "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{_db_dir.name}/test.db"),
        "REDIS_URL": "",
        "JWT_SECRET": "test-secret-0123456789-abcdefghijklmn",
        "TTS_PROVIDER": "mock",
        "STORAGE_BACKEND": "local",
        "ANTHROPIC_API_KEY": "test",
    }
)

import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

import fakeredis  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base, Voice  # noqa: E402
from app.services import pipeline  # noqa: E402
from app.services.queue import FakeQueue  # noqa: E402
from app.services.storage import LocalStorage  # noqa: E402
from app.tts.audio import to_wav_bytes  # noqa: E402
from app.tts.mock import MockProvider  # noqa: E402


@pytest.fixture(autouse=True)
async def db_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    # 每个测试有自己的事件循环，连接不能跨循环复用，测完把连接池清空
    await engine.dispose()


@pytest.fixture
def tmp_storage(monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="echo-test-"))
    monkeypatch.setattr(settings, "cache_dir", root / "_cache")
    yield LocalStorage(root)
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
async def redis():
    r = fakeredis.FakeAsyncRedis()
    yield r
    await r.aclose()


@pytest.fixture
def queue():
    return FakeQueue()


@pytest.fixture
def tts():
    return MockProvider()


@pytest.fixture
def app(tmp_storage, redis, queue, tts):
    application = create_app(use_lifespan=False)
    application.state.storage = tmp_storage
    application.state.redis = redis
    application.state.queue = queue
    application.state.tts = tts
    return application


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def register(client: AsyncClient, email: str = "a@example.com", password: str = "password123") -> dict:
    r = await client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def user_client(client):
    """已登录的客户端（Cookie 由 httpx 自动保存）。"""
    await register(client)
    return client


@pytest.fixture
async def system_voice(tmp_storage):
    path = Path(tmp_storage.root) / "ref.wav"
    path.write_bytes(to_wav_bytes(np.zeros(24000 * 3, dtype="float32"), 24000))
    async with SessionLocal() as db:
        v = Voice(owner_id=None, name="测试音色", ref_audio_path=str(path), ref_text="测试参考文本", tags=["测试"])
        db.add(v)
        await db.commit()
        return v


@pytest.fixture
def deps(tmp_storage, tts, redis):
    return pipeline.Deps(storage=tmp_storage, tts=tts, redis=redis, llm=None)


async def run_worker(queue: FakeQueue, deps: pipeline.Deps) -> None:
    """模拟 Worker：把队列里的任务依次执行完。"""
    while queue.enqueued:
        job_id, _ = queue.enqueued.pop(0)
        async with SessionLocal() as db:
            await pipeline.run(db, job_id, deps)
