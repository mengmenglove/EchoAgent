"""语音聊天：用户发一句话 → 本地 Qwen 回复（流式）→ F5 把回复念出来。

一次请求的流程（全部通过一条 SSE 流推给前端）：
  1. 存用户消息
  2. 带上最近几轮历史调用 Ollama，文字一边生成一边推给前端（"delta" 事件）
  3. 回复写完后存库，推 "text_done"
  4. 按句切分，逐句合成（命中缓存的不重合成），拼成一段 wav，推 "audio"
     合成期间推 "audio_progress"（每句一次）和 "ping"（心跳），防止代理判定空闲断开
  5. 推 "done"

为什么等整段文字写完再合成，而不是边写边合成：F5 一次只能合成一句，
而且模型生成和 F5 合成都用 GPU，同时跑互相拖慢。先文字后语音最简单，
用户也能马上看到文字。
"""

import asyncio
import hashlib
import logging
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.errors import NotFound, TransientError
from app.llm.ollama import OllamaChat
from app.models import ChatMessage, ChatSession, TTSCache, User
from app.services.storage import Storage, tts_cache_key
from app.services.voices import get_accessible, list_accessible, resolve_ref
from app.tts import audio
from app.tts.base import TTSProvider, VoiceRef
from app.tts.chunker import chunk_text
from app.tts.text_norm import is_chinese, normalize

log = logging.getLogger("echo.chat")

SYSTEM_PROMPT = """\
You are Echo, a friendly voice chat partner. Your replies are converted to speech, so:
- Reply in the same language the user writes in (English or Chinese).
- Keep it short and conversational: 1-3 sentences, like talking out loud.
- Plain text only. No markdown, lists, emoji, code, or URLs.
- If the user is practicing English, gently correct obvious mistakes in one short sentence, then keep chatting.
"""

MAX_SENTENCES = 6  # 防止模型话太多，语音合成要等太久
PING_SECONDS = 10.0

# 后台合成任务要有强引用，否则可能被垃圾回收掉
_BACKGROUND: set[asyncio.Task] = set()


def _cache_hash(text: str, voice_id: str, provider: str) -> str:
    raw = f"chat|{text}|{voice_id}|{provider}|{settings.tts_model_version}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------- 会话 ----------


async def get_owned(db: AsyncSession, user: User, session_id: uuid.UUID) -> ChatSession:
    s = await db.get(ChatSession, session_id)
    if s is None or s.user_id != user.id:
        raise NotFound("对话不存在")
    return s


async def create_session(db: AsyncSession, user: User, voice_id: uuid.UUID | None) -> ChatSession:
    if voice_id is None:
        voices = await list_accessible(db, user.id)
        voice_id = voices[0].id if voices else None
    else:
        await get_accessible(db, user.id, voice_id)
    s = ChatSession(user_id=user.id, voice_id=voice_id)
    db.add(s)
    await db.commit()
    return s


async def list_sessions(db: AsyncSession, user: User) -> list[ChatSession]:
    stmt = select(ChatSession).where(ChatSession.user_id == user.id).order_by(ChatSession.updated_at.desc())
    return list((await db.scalars(stmt.limit(50))).all())


async def list_messages(db: AsyncSession, session_id: uuid.UUID) -> list[ChatMessage]:
    stmt = select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
    return list((await db.scalars(stmt)).all())


# ---------- 发消息 ----------


def _system_prompt(user_text: str) -> str:
    # 小模型容易跟着历史的语言走（前面聊英文，用户改说中文它还回英文），
    # 所以每次按用户"这一句"的语言明确告诉它用什么语言回。
    lang = "Chinese (简体中文)" if is_chinese(user_text) else "English"
    return f"{SYSTEM_PROMPT}\nThe user's latest message is in {lang}. Reply in {lang}."


def _history(messages: list[ChatMessage], user_text: str) -> list[dict]:
    recent = messages[-settings.chat_history_turns * 2 :]
    return (
        [{"role": "system", "content": _system_prompt(user_text)}]
        + [{"role": m.role, "content": m.content} for m in recent]
        + [{"role": "user", "content": user_text}]
    )


async def send(
    db: AsyncSession,
    session: ChatSession,
    text: str,
    *,
    llm: OllamaChat,
    tts: TTSProvider,
    storage: Storage,
    speak: bool = True,
) -> AsyncIterator[tuple[str, dict]]:
    """产出 (事件类型, 数据)。由 API 层转成 SSE。"""
    history = await list_messages(db, session.id)
    user_msg = ChatMessage(session_id=session.id, role="user", content=text)
    db.add(user_msg)
    if session.title == "新对话":
        session.title = text.strip().splitlines()[0][:30]
    await db.commit()
    yield "user_saved", {"id": user_msg.id}

    # 1. 文字：流式生成
    parts: list[str] = []
    try:
        async for delta in llm.stream(_history(history, text)):
            parts.append(delta)
            yield "delta", {"text": delta}
    except TransientError as e:
        yield "error", {"message": str(e)}
        return
    reply = "".join(parts).strip()
    if len(reply) > settings.chat_max_reply_chars:
        log.info("reply truncated from %d chars", len(reply))
    if not reply:
        yield "error", {"message": "模型没有回复内容"}
        return

    bot_msg = ChatMessage(session_id=session.id, role="assistant", content=reply)
    db.add(bot_msg)
    await db.commit()

    # 2. 语音：逐句合成后拼接
    if not speak:
        yield "text_done", {"id": bot_msg.id, "text": reply}
        yield "done", {}
        return
    progress: asyncio.Queue[tuple[int, int]] = asyncio.Queue()
    # 合成放进独立任务、用独立的数据库会话，并且在推送文字之前就启动：
    # 前端任何时候断开，这个生成器都会被取消，但语音照样合成完并存库，用户回来还能播放
    task = asyncio.create_task(
        _synthesize_detached(session.id, bot_msg.id, tts=tts, storage=storage, progress=progress)
    )
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    yield "text_done", {"id": bot_msg.id, "text": reply}
    # 合成要几十秒。期间每句推一次进度，没进度时每 PING_SECONDS 推一次心跳，
    # 否则中间的代理（Next.js rewrites、Nginx）会把"长时间没数据"的连接当成超时断掉
    while not task.done() or not progress.empty():
        # 同时等"有新进度"和"合成结束"，谁先到处理谁；都没到就发心跳
        getter = asyncio.ensure_future(progress.get())
        await asyncio.wait({task, getter}, timeout=PING_SECONDS, return_when=asyncio.FIRST_COMPLETED)
        if getter.done():
            done_i, total = getter.result()
            yield "audio_progress", {"done": done_i, "total": total}
        else:
            getter.cancel()
            if not task.done():
                yield "ping", {}
    try:
        ms = task.result()
    except Exception as e:  # 语音失败不影响文字回复
        log.error("chat tts failed: %r", e)
        yield "audio_error", {"message": f"语音合成失败：{e}"}
        yield "done", {}
        return
    yield "audio", {"id": bot_msg.id, "audio_ms": ms}
    yield "done", {}


async def _synthesize_detached(
    session_id: uuid.UUID, message_id: int, *, tts: TTSProvider, storage: Storage, progress: asyncio.Queue
) -> int:
    async with SessionLocal() as db:
        session = await db.get(ChatSession, session_id)
        msg = await db.get(ChatMessage, message_id)
        if session is None or msg is None:
            raise NotFound("对话已删除")
        _, ms = await synthesize_message(db, session, msg, tts=tts, storage=storage, progress=progress)
        return ms


async def synthesize_message(
    db: AsyncSession,
    session: ChatSession,
    msg: ChatMessage,
    *,
    tts: TTSProvider,
    storage: Storage,
    progress: asyncio.Queue | None = None,
) -> tuple[str, int]:
    if session.voice_id is None:
        raise NotFound("没有可用音色，请先执行 seed-voices")
    voice = await get_accessible(db, session.user_id, session.voice_id, include_deleted=True)
    ref: VoiceRef = await resolve_ref(voice, storage)
    user = await db.get(User, session.user_id)
    lexicon = (user.lexicon if user else None) or {}

    chunks = chunk_text(msg.content)[:MAX_SENTENCES]
    parts: list[tuple[bytes, int]] = []
    for i, c in enumerate(chunks):
        # 英文句子的停顿短一点，听起来更自然
        pause = c.pause_ms if is_chinese(c.text) else min(c.pause_ms, 250)
        parts.append((await _synth_cached(db, tts, storage, normalize(c.text, lexicon), ref), pause))
        if progress is not None:
            progress.put_nowait((i + 1, len(chunks)))
    wav, _, _ = audio.concat(parts)

    key = f"users/{session.user_id}/chats/{session.id}/{msg.id}.wav"
    await storage.put(key, wav, "audio/wav")
    _, ms = audio.wav_info(wav)
    msg.audio_key, msg.audio_ms = key, ms
    await db.commit()
    return key, ms


async def _synth_cached(db: AsyncSession, tts: TTSProvider, storage: Storage, text: str, ref: VoiceRef) -> bytes:
    h = _cache_hash(text, ref.id, tts.name)
    cached = await db.get(TTSCache, h)
    if cached and await storage.exists(cached.audio_key):
        return await storage.get(cached.audio_key)
    result = await tts.synthesize(text, ref, 1.0)
    key = tts_cache_key(h)
    await storage.put(key, result.wav_bytes, "audio/wav")
    await db.merge(TTSCache(hash=h, audio_key=key, duration_ms=result.duration_ms, sample_rate=result.sample_rate))
    await db.commit()
    return result.wav_bytes
