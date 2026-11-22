"""任务接口：创建、列表、详情、SSE 进度、追问回答、取消、删除、下载、改稿重生成。"""

import asyncio
import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, get_db
from app.deps import current_user
from app.errors import NotFound
from app.models import TERMINAL_STATUSES, User
from app.schemas import AnswerIn, CreateJobIn, EstimateOut, JobListOut, JobOut, ReviseJobIn
from app.services import billing, events
from app.services import jobs as job_service

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _deps(request: Request):
    s = request.app.state
    return s.redis, s.queue, s.storage


@router.post("/estimate", response_model=EstimateOut)
async def estimate(body: CreateJobIn, _: User = Depends(current_user)):
    """前端实时显示"预计时长 / 预计消耗额度"。"""
    seconds, credits = billing.estimate_credits(body.mode, body.text, body.target_seconds, body.speed)
    return EstimateOut(estimated_seconds=round(seconds, 1), credits=credits)


@router.post("", response_model=JobOut, status_code=202)
async def create_job(
    body: CreateJobIn,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    # 202 Accepted：已收单，正在后台处理。客户端拿 id 去订阅进度
    redis, queue, _ = _deps(request)
    job = await job_service.create(db, redis, queue, user, body)
    return JobOut.from_job(job)


@router.get("", response_model=JobListOut)
async def list_jobs(
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=50),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    items, next_cursor = await job_service.list_for_user(db, user, cursor, limit, q)
    return JobListOut(items=[JobOut.from_job(j) for j in items], next_cursor=next_cursor)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return JobOut.from_job(await job_service.get_owned(db, user, job_id))


def _sse(ev: dict) -> str:
    return f"id: {ev['id']}\nevent: progress\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"


@router.get("/{job_id}/events")
async def job_events(job_id: uuid.UUID, request: Request, user: User = Depends(current_user)):
    """SSE 进度流。

    顺序很重要：先订阅 Redis，再从数据库回放历史，最后转发实时消息，按事件 id 去重。
    如果先回放再订阅，两步之间产生的事件就会丢失。

    这里不用 Depends(get_db)：SSE 是长连接，依赖注入的会话会一直占着连接池。
    改为需要时临时开一个会话，用完立刻关。
    """
    async with SessionLocal() as db:
        job = await job_service.get_owned(db, user, job_id)
        finished = job.status in TERMINAL_STATUSES

    try:
        last_id = int(request.headers.get("last-event-id") or request.query_params.get("last_event_id") or 0)
    except ValueError:
        last_id = 0
    redis = request.app.state.redis

    async def stream():
        pubsub = redis.pubsub() if redis is not None else None
        if pubsub is not None:
            await pubsub.subscribe(events.channel(job_id))
        sent = last_id
        try:
            yield "retry: 3000\n\n"  # 告诉浏览器断线 3 秒后重连
            async with SessionLocal() as db:
                history = await events.events_after(db, job_id, last_id)
            for ev in history:
                sent = ev.id
                yield _sse(events.event_dict(ev))
                if ev.type in events.FINAL_EVENTS:
                    return
            if finished or pubsub is None:
                return
            while not await request.is_disconnected():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                if msg is None:
                    yield ": ping\n\n"  # 心跳注释行，防止代理因空闲断开连接
                    continue
                data = json.loads(msg["data"])
                if data["id"] <= sent:
                    continue
                sent = data["id"]
                yield _sse(data)
                if data["type"] in events.FINAL_EVENTS:
                    return
        except asyncio.CancelledError:
            pass
        finally:
            if pubsub is not None:
                await pubsub.unsubscribe()
                await pubsub.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/{job_id}/answer", response_model=JobOut)
async def answer(
    job_id: uuid.UUID,
    body: AnswerIn,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    redis, queue, _ = _deps(request)
    job = await job_service.get_owned(db, user, job_id)
    return JobOut.from_job(await job_service.answer(db, redis, queue, job, body.answer))


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel(
    job_id: uuid.UUID,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    redis, _, _ = _deps(request)
    job = await job_service.get_owned(db, user, job_id)
    return JobOut.from_job(await job_service.cancel(db, redis, job))


@router.post("/{job_id}/revise", response_model=JobOut, status_code=202)
async def revise(
    job_id: uuid.UUID,
    body: ReviseJobIn,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    redis, queue, _ = _deps(request)
    parent = await job_service.get_owned(db, user, job_id)
    return JobOut.from_job(await job_service.revise(db, redis, queue, user, parent, body))


@router.delete("/{job_id}", status_code=204)
async def delete_job(
    job_id: uuid.UUID,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await job_service.get_owned(db, user, job_id)
    await job_service.delete(db, request.app.state.storage, job)
    return Response(status_code=204)


_FILES = {
    "mp3": ("audio_key", "audio/mpeg"),
    "wav": ("wav_key", "audio/wav"),
    "srt": ("srt_key", "application/x-subrip"),
    "vtt": ("vtt_key", "text/vtt"),
}


@router.get("/{job_id}/file")
async def download(
    job_id: uuid.UUID,
    request: Request,
    format: Literal["mp3", "wav", "srt", "vtt"] = "mp3",
    download: bool = False,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """播放 / 下载。本地存储直接发文件（FileResponse 支持 Range，可以拖动进度条）；
    对象存储跳转到预签名 URL，流量不经过 API 服务器。"""
    job = await job_service.get_owned(db, user, job_id)
    attr, media_type = _FILES[format]
    key = getattr(job, attr)
    if not key:
        raise NotFound("文件还没有生成")
    filename = f"{(job.title or 'echo').strip()[:30] or 'echo'}.{format}"
    storage = request.app.state.storage
    if (path := storage.local_path(key)) is not None:
        if not path.exists():
            raise NotFound("文件不存在")
        return FileResponse(
            path,
            media_type=media_type,
            filename=filename if download else None,
            content_disposition_type="attachment" if download else "inline",
        )
    return RedirectResponse(await storage.presigned_url(key, 3600, filename if download else None))
