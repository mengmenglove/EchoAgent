"""任务的创建、查询、状态流转。

所有状态变化都必须经过 transition()：它校验流转是否合法，并发出 status_changed 事件。
不要在别处直接写 job.status = ...，否则状态一多就乱了。
"""

import base64
import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import AppError, Conflict, NotFound, RateLimited
from app.models import TERMINAL_STATUSES, Job, JobMode, JobStatus, User
from app.schemas import CreateJobIn, ReviseJobIn
from app.services import billing, events
from app.services.queue import JobQueue
from app.services.storage import Storage, job_prefix
from app.services.voices import get_accessible
from app.tts.chunker import chunk_text

S = JobStatus

# 合法的状态流转。同状态（例如 Worker 重试时 writing → writing）也允许。
ALLOWED: dict[str, set[str]] = {
    S.queued: {S.writing, S.synthesizing, S.failed, S.canceled},
    S.writing: {S.needs_input, S.synthesizing, S.failed, S.canceled},
    S.needs_input: {S.queued, S.failed, S.canceled},
    S.synthesizing: {S.verifying, S.succeeded, S.failed, S.canceled},
    S.verifying: {S.succeeded, S.failed, S.canceled},
    S.succeeded: set(),
    S.failed: set(),
    S.canceled: set(),
}


class IllegalTransition(Exception):
    pass


async def transition(db: AsyncSession, redis: Redis | None, job: Job, to: JobStatus, **payload) -> None:
    if job.status == to:
        return
    if to not in ALLOWED[job.status]:
        raise IllegalTransition(f"{job.status} → {to}")
    frm = job.status
    job.status = to
    await events.emit(db, redis, job.id, "status_changed", {"from": frm, "to": to, **payload})


# ---------- 查询 ----------


async def get_owned(db: AsyncSession, user: User, job_id: uuid.UUID) -> Job:
    job = await db.get(Job, job_id)
    # 越权校验：不是自己的任务，一律当作不存在
    if job is None or job.user_id != user.id:
        raise NotFound("任务不存在")
    return job


def _encode_cursor(job: Job) -> str:
    return base64.urlsafe_b64encode(f"{job.created_at.isoformat()}|{job.id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        ts, jid = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(ts), uuid.UUID(jid)
    except Exception as e:
        raise AppError("cursor 无效") from e


async def list_for_user(
    db: AsyncSession, user: User, cursor: str | None, limit: int, q: str | None = None
) -> tuple[list[Job], str | None]:
    """游标分页：按 (created_at, id) 倒序。比 OFFSET 分页稳定，新数据插入不会导致重复或漏条。"""
    stmt = select(Job).where(Job.user_id == user.id)
    if q:
        stmt = stmt.where(Job.title.contains(q) | Job.input_text.contains(q))
    if cursor:
        ts, jid = _decode_cursor(cursor)
        stmt = stmt.where((Job.created_at < ts) | ((Job.created_at == ts) & (Job.id < jid)))
    stmt = stmt.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit + 1)
    rows = list((await db.scalars(stmt)).all())
    next_cursor = _encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    return rows[:limit], next_cursor


# ---------- 创建 ----------


async def _check_limits(db: AsyncSession, redis: Redis | None, user: User) -> None:
    active = await db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.user_id == user.id, Job.status.not_in([s.value for s in TERMINAL_STATUSES]))
    )
    if (active or 0) >= settings.max_active_jobs:
        raise RateLimited(f"同时最多进行 {settings.max_active_jobs} 个任务，请等前面的完成")
    if redis is not None:
        key = f"quota:{user.id}:{datetime.now(UTC):%Y%m%d}"
        n = await redis.incr(key)
        if n == 1:
            await redis.expire(key, 86400)
        if n > settings.daily_job_limit:
            raise RateLimited(f"今天已达到 {settings.daily_job_limit} 次上限")


def _title_from(text: str) -> str:
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first[:30]


async def create(db: AsyncSession, redis: Redis | None, queue: JobQueue, user: User, body: CreateJobIn) -> Job:
    await _check_limits(db, redis, user)
    if body.voice_id:
        await get_accessible(db, user.id, body.voice_id)

    job = Job(
        id=uuid.uuid4(),
        user_id=user.id,
        mode=body.mode,
        input_text=body.text,
        voice_id=body.voice_id,
        speed=body.speed,
        target_seconds=body.target_seconds,
        title=_title_from(body.text),
    )
    if body.mode == JobMode.script:
        # 文案模式在创建时就分好句，前端马上能看到分段
        job.script = [c.as_dict() for c in chunk_text(body.text)]
        if not job.script:
            raise AppError("文案里没有可朗读的内容")
    db.add(job)
    await db.flush()  # 先拿到外键可用的 job 行，再写账本

    _, credits = billing.estimate_credits(body.mode, body.text, body.target_seconds, body.speed)
    await billing.hold(db, job, credits)
    await events.emit(db, redis, job.id, "created", {"credits_held": credits})  # 内部会 commit

    # 一定要先 commit 再入队：否则 Worker 可能比事务先跑，查不到这个任务
    await _enqueue(db, queue, job)
    return job


async def revise(
    db: AsyncSession, redis: Redis | None, queue: JobQueue, user: User, parent: Job, body: ReviseJobIn
) -> Job:
    """改稿重新生成：新建一个文案模式任务，未修改的句子会命中合成缓存。"""
    if parent.status != S.succeeded:
        raise Conflict("只有已完成的任务可以改稿重生成")
    await _check_limits(db, redis, user)
    voice_id = body.voice_id or parent.voice_id
    if voice_id:
        await get_accessible(db, user.id, voice_id)
    text = "".join(s.text for s in body.segments)
    job = Job(
        id=uuid.uuid4(),
        user_id=user.id,
        parent_id=parent.id,
        mode=JobMode.script,
        input_text=text,
        script=[s.model_dump() for s in body.segments],
        voice_id=voice_id,
        speed=body.speed or parent.speed,
        title=parent.title,
    )
    db.add(job)
    await db.flush()
    _, credits = billing.estimate_credits(JobMode.script, text, None, job.speed)
    await billing.hold(db, job, credits)
    await events.emit(db, redis, job.id, "created", {"credits_held": credits, "parent_id": str(parent.id)})
    await _enqueue(db, queue, job)
    return job


async def _enqueue(db: AsyncSession, queue: JobQueue, job: Job) -> None:
    job.enqueue_count += 1
    await db.commit()
    await queue.enqueue(str(job.id), job.enqueue_count)


# ---------- 追问 / 取消 / 删除 ----------


async def answer(db: AsyncSession, redis: Redis | None, queue: JobQueue, job: Job, text: str) -> Job:
    """把用户的回答作为 ask_user 工具的结果，追加到 Agent 对话末尾，然后重新入队。"""
    if job.status != S.needs_input or not job.pending_input:
        raise Conflict("这个任务当前不需要回答问题")
    pending = job.pending_input
    results = list(pending.get("results", []))
    results.append({"type": "tool_result", "tool_use_id": pending["tool_use_id"], "content": text})
    # JSON 列要整体赋新值，SQLAlchemy 才能检测到变化（原地 append 不会触发更新）
    job.agent_messages = [*(job.agent_messages or []), {"role": "user", "content": results}]
    job.pending_input = None
    await events.emit(db, redis, job.id, "answered", {"answer": text})
    await transition(db, redis, job, S.queued)
    await _enqueue(db, queue, job)
    return job


async def cancel(db: AsyncSession, redis: Redis | None, job: Job) -> Job:
    if job.status in TERMINAL_STATUSES:
        raise Conflict("任务已经结束")
    await billing.release(db, job, note="取消")
    await transition(db, redis, job, S.canceled)
    await events.emit(db, redis, job.id, "canceled", {})
    return job


async def delete(db: AsyncSession, storage: Storage, job: Job) -> None:
    if job.status not in TERMINAL_STATUSES:
        raise Conflict("进行中的任务请先取消")
    await storage.delete_prefix(job_prefix(job.user_id, job.id))
    await db.delete(job)
    await db.commit()
