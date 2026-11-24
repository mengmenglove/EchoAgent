"""任务入队的薄封装。API 只依赖 JobQueue 接口，具体实现由配置决定：

- 没配 REDIS_URL：MemoryQueue（memory_queue.py），任务在 API 进程里执行，不需要 Redis 和单独的 Worker
- 配了 REDIS_URL：ArqQueue，任务交给独立的 Worker 进程（app/worker.py）
- 测试：FakeQueue，只记录入队了什么
"""

from typing import Protocol

from arq.connections import ArqRedis


class JobQueue(Protocol):
    async def enqueue(self, job_id: str, attempt: int) -> None: ...


class ArqQueue:
    def __init__(self, pool: ArqRedis):
        self.pool = pool

    async def enqueue(self, job_id: str, attempt: int) -> None:
        # _job_id 让 arq 去重：用户狂点、接口重试都不会重复入队。
        # 但 arq 会保留已完成任务的结果一段时间，同一个 _job_id 在此期间不能再次入队，
        # 所以"回答追问后继续"这类重新入队要换一个 id（带上第几次入队）。
        await self.pool.enqueue_job("run_job", job_id, _job_id=f"{job_id}:{attempt}")


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, int]] = []

    async def enqueue(self, job_id: str, attempt: int) -> None:
        self.enqueued.append((job_id, attempt))
