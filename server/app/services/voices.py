"""音色：查询可用音色，并把音色解析成 TTS 可用的本地文件。"""

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import NotFound
from app.models import Voice
from app.services.storage import Storage
from app.tts.base import VoiceRef


async def list_accessible(db: AsyncSession, user_id: uuid.UUID) -> list[Voice]:
    """系统音色 + 我自己的音色。"""
    stmt = (
        select(Voice)
        .where(or_(Voice.owner_id.is_(None), Voice.owner_id == user_id), Voice.deleted_at.is_(None))
        .order_by(Voice.owner_id.is_(None).desc(), Voice.created_at)
    )
    return list((await db.scalars(stmt)).all())


async def get_accessible(
    db: AsyncSession, user_id: uuid.UUID, voice_id: uuid.UUID, *, include_deleted: bool = False
) -> Voice:
    voice = await db.get(Voice, voice_id)
    if voice is None or (voice.owner_id is not None and voice.owner_id != user_id):
        raise NotFound("音色不存在")  # 别人的音色也报"不存在"，不泄露它的存在
    if voice.deleted_at is not None and not include_deleted:
        raise NotFound("音色已删除")
    return voice


async def resolve_ref(voice: Voice, storage: Storage) -> VoiceRef:
    """系统音色直接用本地路径；用户音色从存储下载到本机缓存目录（Worker 可能和 API 不在同一台机器）。"""
    if voice.ref_audio_path:
        path = voice.ref_audio_path
    elif voice.ref_audio_key:
        local = storage.local_path(voice.ref_audio_key)
        if local is not None:
            path = str(local)
        else:
            cached = Path(settings.cache_dir) / "voices" / f"{voice.id}.wav"
            if not cached.exists():
                data = await storage.get(voice.ref_audio_key)
                await asyncio.to_thread(cached.parent.mkdir, parents=True, exist_ok=True)
                await asyncio.to_thread(cached.write_bytes, data)
            path = str(cached)
    else:
        raise NotFound(f"音色 {voice.name} 没有参考音频")
    return VoiceRef(id=str(voice.id), ref_audio_path=path, ref_text=voice.ref_text)
