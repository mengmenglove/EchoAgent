"""执行一个任务：MemoryQueue（API 进程内）和 arq Worker（独立进程）共用这份逻辑。"""

import logging
import uuid

import httpx
from redis.asyncio import Redis

from app.config import settings
from app.db import SessionLocal
from app.errors import TransientError
from app.llm.client import get_llm
from app.services import pipeline
from app.services.storage import make_storage
from app.tts.factory import make_tts

log = logging.getLogger("echo.runner")


def make_http() -> httpx.AsyncClient:
    # 全局复用一个客户端（连接池）。连接超时要短（快速发现服务没起），读超时要长（合成要时间）
    return httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5))


def build_deps(http: httpx.AsyncClient, redis: Redis | None) -> pipeline.Deps:
    asr = None
    if settings.verify_enabled:
        from app.tts.verify import make_asr

        asr = make_asr()
    deps = pipeline.Deps(
        storage=make_storage(settings),
        tts=make_tts(settings, http),
        redis=redis,
        llm=get_llm(),
        asr=asr,
    )
    log.info("runner ready: tts=%s model=%s", deps.tts.name, settings.llm_model)
    return deps


async def run_once(job_id: str, tries: int, deps: pipeline.Deps) -> float | None:
    """跑一次任务。返回 None 表示结束；返回秒数表示遇到临时错误，应该过这么久再试一次。"""
    try:
        async with SessionLocal() as db:
            await pipeline.run(db, job_id, deps)
    except TransientError as e:
        if tries < settings.job_max_tries:
            log.warning("job %s transient error (try %s): %s", job_id, tries, e)
            return 15.0 * tries  # 15 秒、30 秒……退避
        await fail(uuid.UUID(job_id), f"重试 {tries} 次后仍失败：{e}", deps)
    return None


async def fail(job_id: uuid.UUID, message: str, deps: pipeline.Deps) -> None:
    async with SessionLocal() as db:
        await pipeline.fail(db, job_id, message, deps.redis)
