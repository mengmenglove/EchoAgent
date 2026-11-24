"""任务流水线：Worker 拿到任务 ID 后调用 run()。

    queued ─┬─(brief)→ writing ─(Agent 定稿)→ synthesizing → [verifying] → succeeded
            └─(script)──────────────────────→ synthesizing ↗

设计要点：
- 幂等：任务可能被重试。已结束的直接返回；每句合成结果进缓存，重跑不会重复合成。
- 可取消：每合成完一句都检查一次状态。
- 失败可见：任何异常都会把任务标成 failed 并退还额度，用户不会看到一直转圈的任务。
- TransientError（F5 没响应、模型限流）不在这里处理，抛给 Worker 决定是否重试。
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass

import anthropic
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop import AgentError, NeedsInput, run_agent
from app.config import settings
from app.db import get_for_update
from app.errors import JobCanceled, TransientError
from app.models import TERMINAL_STATUSES, Job, JobMode, JobStatus, TTSCache, User, Voice
from app.services import billing, events
from app.services.jobs import transition
from app.services.storage import Storage, job_prefix, tts_cache_key
from app.services.voices import get_accessible, resolve_ref
from app.tts import audio, subtitles
from app.tts.base import TTSProvider, VoiceRef
from app.tts.chunker import chunk_segments
from app.tts.text_norm import normalize
from app.tts.verify import ASRProvider, cer

log = logging.getLogger(__name__)
S = JobStatus


@dataclass
class Deps:
    """流水线需要的外部依赖。Worker 在启动时创建一次；测试里换成假实现。"""

    storage: Storage
    tts: TTSProvider
    redis: Redis | None
    llm: anthropic.AsyncAnthropic | None = None
    asr: ASRProvider | None = None


async def _lock_job(db: AsyncSession, job_id: uuid.UUID) -> Job | None:
    """重新读取并锁住任务行：拿到最新状态（可能已被用户取消），避免和 API 并发修改冲突。"""
    return await get_for_update(db, Job, job_id)


async def _ensure_not_canceled(db: AsyncSession, job_id: uuid.UUID) -> None:
    status = await db.scalar(select(Job.status).where(Job.id == job_id).execution_options(populate_existing=True))
    if status == S.canceled:
        raise JobCanceled()


async def run(db: AsyncSession, job_id: str, deps: Deps) -> None:
    jid = uuid.UUID(job_id)
    job = await _lock_job(db, jid)
    if job is None or job.status in TERMINAL_STATUSES or job.status == S.needs_input:
        return  # 幂等：已结束、已删除、或在等用户回答
    await db.commit()  # 立刻放锁：后面要等模型和 F5 很久，不能一直锁着

    async def emit(type_: str, payload: dict) -> None:
        await events.emit(db, deps.redis, job.id, type_, payload)

    try:
        if job.mode == JobMode.brief and not job.script:
            await _write_script(db, job, deps, emit)

        await transition(db, deps.redis, job, S.synthesizing)
        texts, wav_parts = await _synthesize(db, job, deps, emit)
        await _finalize_audio(db, job, deps, texts, wav_parts)

        if settings.verify_enabled and deps.asr is not None:
            await transition(db, deps.redis, job, S.verifying)
            await _verify(job, deps, wav_parts, emit)

        # 收尾前再锁一次：如果这期间用户取消了，就不再结算（取消时已退款）
        job = await _lock_job(db, jid)
        if job is None or job.status == S.canceled:
            return
        await billing.settle(db, job)
        await transition(db, deps.redis, job, S.succeeded)
        await emit("succeeded", {"duration_ms": job.duration_ms, "credits_charged": job.credits_charged})

    except NeedsInput as q:
        job.pending_input = {"tool_use_id": q.tool_use_id, "questions": q.questions, "results": q.results}
        await transition(db, deps.redis, job, S.needs_input)
        await emit("question", {"questions": q.questions})

    except JobCanceled:
        log.info("job %s canceled during processing", job_id)

    except AgentError as e:
        await fail(db, jid, str(e), deps.redis)

    except TransientError:
        await db.rollback()
        raise  # 交给 Worker 决定是否重试

    except Exception as e:
        log.exception("job %s failed", job_id)
        await fail(db, jid, f"内部错误：{e}", deps.redis)


async def fail(db: AsyncSession, job_id: uuid.UUID, message: str, redis: Redis | None) -> None:
    """把任务标为失败并退还额度。可以被重复调用。"""
    await db.rollback()  # 丢弃失败前未提交的半截修改
    job = await _lock_job(db, job_id)
    if job is None or job.status in TERMINAL_STATUSES:
        return
    job.error = message[:2000]
    await billing.release(db, job, note="失败退款")
    await transition(db, redis, job, S.failed, error=job.error)
    await events.emit(db, redis, job.id, "failed", {"error": job.error})


# ---------- 写稿 ----------


async def _write_script(db: AsyncSession, job: Job, deps: Deps, emit) -> None:
    if deps.llm is None:
        raise AgentError("没有配置大模型（ANTHROPIC_API_KEY），无法使用需求模式")
    await transition(db, deps.redis, job, S.writing)
    result = await run_agent(deps.llm, db, job, emit)
    job.title = result.title
    job.script = [s.model_dump() for s in result.segments]
    job.voice_id = result.voice_id
    job.speed = result.speed
    await emit("script_ready", {"title": job.title, "segments": job.script})


# ---------- 合成 ----------


def _cache_hash(text: str, voice_id: str, speed: float, provider: str) -> str:
    raw = f"{text}|{voice_id}|{speed:.2f}|{provider}|{settings.tts_model_version}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def _synth_one(db: AsyncSession, deps: Deps, text: str, ref: VoiceRef, speed: float) -> tuple[bytes, bool]:
    """合成一句。返回 (wav, 是否命中缓存)。"""
    h = _cache_hash(text, ref.id, speed, deps.tts.name)
    cached = await db.get(TTSCache, h)
    if cached and await deps.storage.exists(cached.audio_key):
        return await deps.storage.get(cached.audio_key), True

    result = await deps.tts.synthesize(text, ref, speed)
    key = tts_cache_key(h)
    await deps.storage.put(key, result.wav_bytes, "audio/wav")
    await db.merge(TTSCache(hash=h, audio_key=key, duration_ms=result.duration_ms, sample_rate=result.sample_rate))
    return result.wav_bytes, False


async def _synthesize(db: AsyncSession, job: Job, deps: Deps, emit) -> tuple[list[str], list[tuple[bytes, int]]]:
    if job.voice_id is None:
        raise AgentError("没有选择音色")
    voice: Voice = await get_accessible(db, job.user_id, job.voice_id, include_deleted=True)
    ref = await resolve_ref(voice, deps.storage)
    user = await db.get(User, job.user_id)
    lexicon = (user.lexicon if user else None) or {}

    chunks = chunk_segments(job.script or [])
    if not chunks:
        raise AgentError("文案为空")
    # 分句结果写回 script，前端逐句展示、字幕都以它为准
    job.script = [c.as_dict() for c in chunks]
    await db.commit()  # 合成一句要好几秒，先提交，别让写事务一直开着挡住其他请求

    wav_parts: list[tuple[bytes, int]] = []
    for i, c in enumerate(chunks):
        await _ensure_not_canceled(db, job.id)
        wav, hit = await _synth_one(db, deps, normalize(c.text, lexicon), ref, job.speed)
        wav_parts.append((wav, c.pause_ms))
        await emit("tts_segment_done", {"index": i, "total": len(chunks), "cached": hit})
    return [c.text for c in chunks], wav_parts


async def _finalize_audio(db: AsyncSession, job: Job, deps: Deps, texts: list[str], wav_parts) -> None:
    await _ensure_not_canceled(db, job.id)
    wav, _rate, spans = audio.concat(wav_parts)
    wav = await audio.loudnorm_wav(wav)
    mp3 = await audio.wav_to_mp3(wav)

    prefix = job_prefix(job.user_id, job.id)
    job.wav_key, job.audio_key = f"{prefix}/final.wav", f"{prefix}/final.mp3"
    job.srt_key, job.vtt_key = f"{prefix}/final.srt", f"{prefix}/final.vtt"
    await deps.storage.put(job.wav_key, wav, "audio/wav")
    await deps.storage.put(job.audio_key, mp3, "audio/mpeg")
    await deps.storage.put(job.srt_key, subtitles.to_srt(texts, spans).encode(), "application/x-subrip")
    await deps.storage.put(job.vtt_key, subtitles.to_vtt(texts, spans).encode(), "text/vtt")
    _, job.duration_ms = audio.wav_info(wav)
    job.spans = spans
    await db.commit()


# ---------- 质检 ----------


async def _verify(job: Job, deps: Deps, wav_parts, emit) -> None:
    assert deps.asr is not None
    report = []
    for i, (seg, (wav, _)) in enumerate(zip(job.script or [], wav_parts, strict=True)):
        heard = await deps.asr.transcribe(wav)
        score = cer(normalize(seg["text"]), heard)
        report.append(
            {
                "index": i,
                "heard": heard,
                "cer": round(score, 3),
                "flag": score > settings.verify_cer_threshold,
            }
        )
    job.verify_report = report
    flagged = sum(r["flag"] for r in report)
    await emit("verified", {"flagged": flagged, "total": len(report)})
