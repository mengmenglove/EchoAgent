"""进程内任务队列：不用 Redis 时由它执行任务（配了 REDIS_URL 则用 ArqQueue + Worker）。

单独一个文件，是因为它要调用流水线，而流水线又依赖 services/jobs.py → queue.py，放一起会循环导入。
"""

import asyncio
import contextlib
import logging
import uuid

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Job, JobStatus
from app.services import runner
from app.services.pipeline import Deps

log = logging.getLogger("echo.queue")


class MemoryQueue:
    """进程内队列：一个 asyncio.Queue 加一个后台协程，一次只跑一个任务（F5 只能串行）。

    队列在内存里，进程重启就没了。但任务状态以数据库为准，所以启动时把数据库里
    没做完的任务重新入队即可，已合成的句子会命中缓存，不会重做。

    限制：API 只能开一个进程（不能用 uvicorn --workers N），否则每个进程都会去跑未完成的任务。
    """

    def __init__(self, deps: Deps):
        self.deps = deps
        self._queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def enqueue(self, job_id: str, attempt: int) -> None:
        self._queue.put_nowait((job_id, 1))  # 1 = 第一次尝试

    async def start(self) -> None:
        await self._recover()
        self._task = asyncio.create_task(self._consume(), name="memory-queue")

    async def stop(self) -> None:
        """取消正在跑的任务。它在数据库里还是未完成状态，下次启动会接着做。"""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _recover(self) -> None:
        # needs_input 不算：它在等用户回答，回答后会重新入队
        unfinished = [JobStatus.queued, JobStatus.writing, JobStatus.synthesizing, JobStatus.verifying]
        async with SessionLocal() as db:
            ids = (await db.scalars(select(Job.id).where(Job.status.in_(unfinished)).order_by(Job.created_at))).all()
        for job_id in ids:
            self._queue.put_nowait((str(job_id), 1))
        if ids:
            log.info("恢复 %d 个未完成的任务", len(ids))

    async def _consume(self) -> None:
        while True:
            job_id, tries = await self._queue.get()
            try:
                await self._run(job_id, tries)
            except Exception:  # 一个任务出问题不能让整个队列停掉
                log.exception("job %s crashed", job_id)

    async def _run(self, job_id: str, tries: int) -> None:
        try:
            async with asyncio.timeout(settings.job_timeout_seconds):
                delay = await runner.run_once(job_id, tries, self.deps)
        except TimeoutError:
            await runner.fail(uuid.UUID(job_id), "任务超时", self.deps)
            return
        if delay is not None:
            # 到点再放回队列，等待期间不耽误后面的任务
            asyncio.get_running_loop().call_later(delay, self._queue.put_nowait, (job_id, tries + 1))
