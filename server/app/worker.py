"""arq Worker：从 Redis 取任务并执行流水线。只有配置了 REDIS_URL 才需要它；
没配的话任务直接在 API 进程里执行（见 services/queue.py 的 MemoryQueue）。

启动：  uv run arq app.worker.WorkerSettings
开发：  uv run arq app.worker.WorkerSettings --watch app   （改代码自动重启）

本地 F5 一次只能稳定跑一个合成，所以 max_jobs=1。换成云端 TTS 后可以调大。
"""

import logging

from arq import Retry
from arq.connections import RedisSettings

from app.config import settings
from app.services import runner

if not settings.redis_url:
    raise SystemExit("没有配置 REDIS_URL：任务会在 API 进程里执行，不需要启动 Worker。")


async def startup(ctx: dict) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ctx["http"] = runner.make_http()
    ctx["deps"] = runner.build_deps(ctx["http"], ctx["redis"])  # arq 自带的 Redis 连接，直接拿来 publish 进度


async def shutdown(ctx: dict) -> None:
    # startup 中途失败时 http 可能还没创建，用 get 而不是 ctx["http"]
    if (http := ctx.get("http")) is not None:
        await http.aclose()


async def run_job(ctx: dict, job_id: str) -> None:
    delay = await runner.run_once(job_id, ctx.get("job_try", 1), ctx["deps"])
    if delay is not None:
        raise Retry(defer=delay)


class WorkerSettings:
    functions = [run_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 1
    job_timeout = settings.job_timeout_seconds
    max_tries = settings.job_max_tries
    keep_result = 3600
