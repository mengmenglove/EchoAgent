"""arq Worker：从 Redis 取任务并执行流水线。

启动：  uv run arq app.worker.WorkerSettings
开发：  uv run arq app.worker.WorkerSettings --watch app   （改代码自动重启）

本地 F5 一次只能稳定跑一个合成，所以 max_jobs=1。换成云端 TTS 后可以调大。
"""

import logging
import uuid

import httpx
from arq import Retry
from arq.connections import RedisSettings

from app.config import settings
from app.db import SessionLocal
from app.errors import TransientError
from app.llm.client import get_llm
from app.services import pipeline
from app.services.storage import make_storage
from app.tts.factory import make_tts

log = logging.getLogger("echo.worker")


async def startup(ctx: dict) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # 全局复用一个 httpx 客户端（连接池）。连接超时要短（快速发现服务没起），读超时要长（合成要时间）
    ctx["http"] = httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5))
    asr = None
    if settings.verify_enabled:
        from app.tts.verify import make_asr

        asr = make_asr()
    ctx["deps"] = pipeline.Deps(
        storage=make_storage(settings),
        tts=make_tts(settings, ctx["http"]),
        redis=ctx["redis"],  # arq 自带的 Redis 连接，直接拿来 publish 进度
        llm=get_llm(),
        asr=asr,
    )
    log.info("worker ready: tts=%s model=%s", ctx["deps"].tts.name, settings.llm_model)


async def shutdown(ctx: dict) -> None:
    # startup 中途失败时 http 可能还没创建，用 get 而不是 ctx["http"]
    if (http := ctx.get("http")) is not None:
        await http.aclose()


async def run_job(ctx: dict, job_id: str) -> None:
    deps: pipeline.Deps = ctx["deps"]
    try:
        async with SessionLocal() as db:
            await pipeline.run(db, job_id, deps)
    except TransientError as e:
        tries = ctx.get("job_try", 1)
        if tries < settings.job_max_tries:
            log.warning("job %s transient error (try %s): %s", job_id, tries, e)
            raise Retry(defer=15 * tries) from e  # 15 秒、30 秒……后重试
        async with SessionLocal() as db:
            await pipeline.fail(db, uuid.UUID(job_id), f"重试 {tries} 次后仍失败：{e}", deps.redis)


class WorkerSettings:
    functions = [run_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 1
    job_timeout = settings.job_timeout_seconds
    max_tries = settings.job_max_tries
    keep_result = 3600
