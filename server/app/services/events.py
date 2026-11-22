"""进度事件：先写数据库（可靠），再通过 Redis 广播（实时）。

SSE 端点订阅 Redis 频道 job:{id} 拿实时消息；断线重连时，从数据库回放
id > Last-Event-ID 的事件。所以即使 Redis 消息丢了，用户也不会漏看进度。
"""

import json
import uuid

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import JobEvent

# 收到这些事件后，前端和 SSE 流都可以结束
FINAL_EVENTS = {"succeeded", "failed", "canceled"}


def channel(job_id: uuid.UUID | str) -> str:
    return f"job:{job_id}"


def event_dict(ev: JobEvent) -> dict:
    return {"id": ev.id, "type": ev.type, "payload": ev.payload}


async def emit(db: AsyncSession, redis: Redis | None, job_id: uuid.UUID, type_: str, payload: dict | None = None):
    ev = JobEvent(job_id=job_id, type=type_, payload=payload or {})
    db.add(ev)
    await db.commit()  # 拿到自增 id，同时把之前对 job 的修改一起提交
    if redis is not None:
        try:
            await redis.publish(channel(job_id), json.dumps(event_dict(ev), ensure_ascii=False))
        except Exception:  # 广播失败不影响主流程，前端会从数据库补齐
            pass
    return ev


async def events_after(db: AsyncSession, job_id: uuid.UUID, last_id: int) -> list[JobEvent]:
    stmt = select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.id > last_id).order_by(JobEvent.id)
    return list((await db.scalars(stmt)).all())
