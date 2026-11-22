"""音色：列表、试听样音、上传自定义音色。"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import current_user
from app.errors import AppError, NotFound
from app.models import User, Voice
from app.schemas import VoiceOut
from app.services.storage import voice_key
from app.services.voices import get_accessible, list_accessible
from app.tts.audio import transcode_upload, wav_info

router = APIRouter(prefix="/api/voices", tags=["voices"])

MAX_UPLOAD = 10 * 1024 * 1024


def _out(v: Voice, user: User) -> VoiceOut:
    out = VoiceOut.model_validate(v)
    out.is_mine = v.owner_id == user.id
    return out


@router.get("", response_model=list[VoiceOut])
async def list_voices(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return [_out(v, user) for v in await list_accessible(db, user.id)]


@router.get("/{voice_id}/sample")
async def voice_sample(
    voice_id: uuid.UUID,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """试听：直接返回参考音频。"""
    voice = await get_accessible(db, user.id, voice_id)
    storage = request.app.state.storage
    if voice.ref_audio_path and Path(voice.ref_audio_path).exists():  # noqa: ASYNC240  stat 一个本地小文件，耗时可忽略
        return FileResponse(voice.ref_audio_path, media_type="audio/wav")
    if voice.ref_audio_key:
        if (p := storage.local_path(voice.ref_audio_key)) is not None:
            return FileResponse(p, media_type="audio/wav")
        return RedirectResponse(await storage.presigned_url(voice.ref_audio_key, 600))
    raise NotFound("样音不存在")


@router.post("", response_model=VoiceOut, status_code=201)
async def create_voice(
    request: Request,
    name: str = Form(min_length=1, max_length=32),
    ref_text: str = Form(min_length=2, max_length=300, description="录音里念的原文，必须逐字一致"),
    consent: bool = Form(description="我确认拥有该声音的使用权，或已获得声音本人的授权"),
    tags: str = Form(default="", description="逗号分隔"),
    file: UploadFile = File(),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if not consent:
        raise AppError("请先确认拥有该声音的使用权", code="consent_required")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise AppError("文件不能超过 10MB")
    try:
        wav = await transcode_upload(data)  # 不信任原文件，统一重新转码
    except RuntimeError as e:
        raise AppError("无法识别的音频文件") from e
    _, ms = wav_info(wav)
    if not 3000 <= ms <= 30000:
        raise AppError(f"参考音频要在 3~30 秒之间，当前 {ms / 1000:.1f} 秒")

    voice = Voice(
        id=uuid.uuid4(),
        owner_id=user.id,
        name=name,
        tags=[t.strip() for t in tags.split(",") if t.strip()][:8],
        ref_text=ref_text.strip(),
        consent_at=datetime.now(UTC),
    )
    voice.ref_audio_key = voice_key(user.id, voice.id)
    await request.app.state.storage.put(voice.ref_audio_key, wav, "audio/wav")
    db.add(voice)
    await db.commit()
    return _out(voice, user)


@router.delete("/{voice_id}", status_code=204)
async def delete_voice(voice_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    voice = await db.get(Voice, voice_id)
    if voice is None or voice.owner_id != user.id or voice.deleted_at is not None:
        raise NotFound("音色不存在")
    voice.deleted_at = datetime.now(UTC)  # 软删除：参考音频保留，历史任务"改一句重生成"仍可用
    await db.commit()
