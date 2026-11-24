"""不用 Redis 的模式：进程内队列执行任务、中断恢复、SSE 轮询、每日次数限制。"""

import asyncio
import uuid

import pytest

from app.config import settings
from app.db import SessionLocal
from app.errors import TransientError
from app.main import create_app
from app.models import Job, JobStatus
from app.services import runner
from app.services.memory_queue import MemoryQueue
from tests.conftest import register

SCRIPT = "今天给大家介绍一款咖啡机。它只要三分钟就能做好一杯拿铁！"


@pytest.fixture
def redis():
    return None  # 覆盖 conftest 里的 fakeredis


@pytest.fixture
async def mq(app, deps):
    q = MemoryQueue(deps)
    app.state.queue = q
    await q.start()
    yield q
    await q.stop()


async def create(client, voice) -> str:
    r = await client.post("/api/jobs", json={"mode": "script", "text": SCRIPT, "voice_id": str(voice.id)})
    assert r.status_code == 202, r.text
    return r.json()["id"]


async def wait_for(client, job_id: str, status: str) -> dict:
    async with asyncio.timeout(15):
        while True:
            job = (await client.get(f"/api/jobs/{job_id}")).json()
            if job["status"] == status:
                return job
            assert job["status"] not in ("failed", "succeeded", "canceled"), job
            await asyncio.sleep(0.05)


async def test_job_runs_in_process(user_client, system_voice, mq):
    job = await wait_for(user_client, await create(user_client, system_voice), "succeeded")
    assert job["has_audio"] and job["credits_charged"] > 0


async def test_sse_streams_live_events_by_polling(user_client, system_voice, mq, deps, monkeypatch):
    gate = asyncio.Event()
    real = deps.tts.synthesize

    async def slow(*a):
        await gate.wait()
        return await real(*a)

    monkeypatch.setattr(deps.tts, "synthesize", slow)
    job_id = await create(user_client, system_voice)
    # 先连上 SSE，再放行合成：后面的事件只能靠轮询拿到
    stream = asyncio.create_task(user_client.get(f"/api/jobs/{job_id}/events"))
    await asyncio.sleep(0.8)
    assert not stream.done()
    gate.set()
    async with asyncio.timeout(15):
        body = (await stream).text
    assert body.count("tts_segment_done") == 2 and '"type": "succeeded"' in body
    ids = [int(line[4:]) for line in body.splitlines() if line.startswith("id: ")]
    assert ids == sorted(set(ids))


@pytest.mark.parametrize("status", ["queued", "synthesizing", "verifying"])
async def test_unfinished_jobs_recovered_on_start(user_client, system_voice, queue, deps, status):
    job_id = await create(user_client, system_voice)  # 进了 FakeQueue，没人执行，相当于进程中断
    async with SessionLocal() as db:
        job = await db.get(Job, uuid.UUID(job_id))
        job.status = JobStatus(status)
        await db.commit()
    q = MemoryQueue(deps)
    await q.start()
    await wait_for(user_client, job_id, "succeeded")
    await q.stop()


async def test_stop_midway_then_resume(user_client, system_voice, mq, deps, tts, monkeypatch):
    real, started = deps.tts.synthesize, asyncio.Event()

    async def hang_on_second(text, *a):
        if len(tts.calls) == 1:
            started.set()
            await asyncio.sleep(60)
        return await real(text, *a)

    monkeypatch.setattr(deps.tts, "synthesize", hang_on_second)
    job_id = await create(user_client, system_voice)
    await started.wait()
    # 合成期间没有占着写锁：其他写请求照常
    async with asyncio.timeout(3):
        assert (await user_client.put("/api/me/lexicon", json={"entries": {"a": "b"}})).status_code == 200
    await mq.stop()
    assert (await user_client.get(f"/api/jobs/{job_id}")).json()["status"] == "synthesizing"

    monkeypatch.setattr(deps.tts, "synthesize", real)
    q = MemoryQueue(deps)
    await q.start()
    await wait_for(user_client, job_id, "succeeded")
    await q.stop()
    assert len(tts.calls) == 2  # 第一句命中缓存，没有重新合成


async def test_transient_error_retries_then_fails_with_refund(user_client, system_voice, mq, deps, monkeypatch):
    calls = 0

    async def down(*_):
        nonlocal calls
        calls += 1
        raise TransientError("F5 没启动")

    real_once = runner.run_once

    async def no_wait(*a):
        return 0 if await real_once(*a) is not None else None

    monkeypatch.setattr(deps.tts, "synthesize", down)
    monkeypatch.setattr(runner, "run_once", no_wait)
    job = await wait_for(user_client, await create(user_client, system_voice), "failed")
    assert calls == settings.job_max_tries and "F5 没启动" in job["error"]
    assert (await user_client.get("/api/me")).json()["credits_balance"] == settings.signup_credits


async def test_timeout_fails_job_and_queue_survives(user_client, system_voice, mq, deps, monkeypatch):
    real = deps.tts.synthesize

    async def hang(*_):
        await asyncio.sleep(60)

    monkeypatch.setattr(settings, "job_timeout_seconds", 0.3)
    monkeypatch.setattr(deps.tts, "synthesize", hang)
    job = await wait_for(user_client, await create(user_client, system_voice), "failed")
    assert job["error"] == "任务超时"

    monkeypatch.setattr(settings, "job_timeout_seconds", 60)
    monkeypatch.setattr(deps.tts, "synthesize", real)
    await wait_for(user_client, await create(user_client, system_voice), "succeeded")


async def test_daily_limit_counts_from_db(user_client, system_voice, monkeypatch):
    monkeypatch.setattr(settings, "daily_job_limit", 1)
    await create(user_client, system_voice)
    r = await user_client.post("/api/jobs", json={"mode": "script", "text": SCRIPT, "voice_id": str(system_voice.id)})
    assert r.status_code == 429 and "今天" in r.json()["error"]["message"]


async def test_health_ok_without_redis(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "db": True, "redis": None, "tts": True}


async def test_timestamps_carry_timezone(client):
    from datetime import datetime

    await register(client)
    created = (await client.get("/api/me")).json()["created_at"]
    assert datetime.fromisoformat(created).utcoffset() is not None  # 没有时区的话，浏览器会差 8 小时


async def test_lifespan_starts_without_redis(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    app = create_app()
    async with app.router.lifespan_context(app):
        assert app.state.redis is None and isinstance(app.state.queue, MemoryQueue)
