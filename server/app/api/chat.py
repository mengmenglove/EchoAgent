"""语音聊天接口。

POST /api/chat/sessions/{id}/messages 直接返回一条 SSE 流：
  event: user_saved   {"id"}
  event: delta        {"text"}         模型一边写一边推
  event: text_done    {"id", "text"}   文字回复完整了
  event: audio_progress {"done", "total"} 每合成完一句
  event: ping                         心跳（合成期间没进度时每 10 秒一次）
  event: audio        {"id", "audio_ms"} 语音合成好了，去 GET .../messages/{id}/audio 取
  event: error / audio_error {"message"}
  event: done
"""

import json
import uuid

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, get_db
from app.deps import current_user
from app.errors import NotFound
from app.models import ChatMessage, User
from app.schemas import ChatMessageIn, ChatMessageOut, ChatSessionIn, ChatSessionOut, ChatSessionPatch
from app.services import chat as chat_service
from app.services.voices import get_accessible

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/sessions", response_model=list[ChatSessionOut])
async def list_sessions(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await chat_service.list_sessions(db, user)


@router.post("/sessions", response_model=ChatSessionOut, status_code=201)
async def create_session(body: ChatSessionIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await chat_service.create_session(db, user, body.voice_id)


@router.patch("/sessions/{session_id}", response_model=ChatSessionOut)
async def update_session(
    session_id: uuid.UUID,
    body: ChatSessionPatch,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    s = await chat_service.get_owned(db, user, session_id)
    await get_accessible(db, user.id, body.voice_id)
    s.voice_id = body.voice_id
    await db.commit()
    return s


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    s = await chat_service.get_owned(db, user, session_id)
    await request.app.state.storage.delete_prefix(f"users/{user.id}/chats/{s.id}")
    await db.delete(s)
    await db.commit()
    return Response(status_code=204)


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
async def list_messages(session_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await chat_service.get_owned(db, user, session_id)
    return [ChatMessageOut.from_msg(m) for m in await chat_service.list_messages(db, session_id)]


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: uuid.UUID, body: ChatMessageIn, request: Request, user: User = Depends(current_user)
):
    # 先校验归属，再开流：出错时能返回正常的 404，而不是一条半截的流
    async with SessionLocal() as db:
        await chat_service.get_owned(db, user, session_id)
    state = request.app.state

    async def stream():
        # 流里自己开会话：要持续几十秒，不能用请求依赖注入的会话
        async with SessionLocal() as db:
            session = await chat_service.get_owned(db, user, session_id)
            async for event, data in chat_service.send(
                db, session, body.text, llm=state.chat_llm, tts=state.tts, storage=state.storage, speak=body.speak
            ):
                yield _sse(event, data)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.get("/sessions/{session_id}/messages/{message_id}/audio")
async def message_audio(
    session_id: uuid.UUID,
    message_id: int,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await chat_service.get_owned(db, user, session_id)
    msg = await db.get(ChatMessage, message_id)
    if msg is None or msg.session_id != session_id or not msg.audio_key:
        raise NotFound("语音不存在")
    storage = request.app.state.storage
    if (path := storage.local_path(msg.audio_key)) is not None:
        return FileResponse(path, media_type="audio/wav")
    return RedirectResponse(await storage.presigned_url(msg.audio_key, 3600))
