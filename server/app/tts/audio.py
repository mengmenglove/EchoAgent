"""音频处理：拼接、静音、响度标准化、转 mp3。"""

import asyncio
import io

import numpy as np
import soundfile as sf


def read_wav(data: bytes) -> tuple[np.ndarray, int]:
    samples, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
    if samples.ndim == 2:  # 立体声 → 单声道
        samples = samples.mean(axis=1)
    return samples, rate


def wav_info(data: bytes) -> tuple[int, int]:
    """返回 (采样率, 时长毫秒)。只读文件头，很快。"""
    info = sf.info(io.BytesIO(data))
    return info.samplerate, int(info.frames * 1000 / info.samplerate)


def to_wav_bytes(samples: np.ndarray, rate: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, samples, rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _resample(samples: np.ndarray, src: int, dst: int) -> np.ndarray:
    """线性插值重采样。只用于兜底（正常情况下同一音色输出采样率一致）。"""
    if src == dst:
        return samples
    n = int(len(samples) * dst / src)
    return np.interp(np.linspace(0, len(samples), n, endpoint=False), np.arange(len(samples)), samples).astype(
        "float32"
    )


def concat(parts: list[tuple[bytes, int]]) -> tuple[bytes, int, list[list[int]]]:
    """把 [(wav_bytes, 之后停顿毫秒)] 拼成一段。

    返回 (完整 wav, 采样率, 每段的 [start_ms, end_ms])。
    采样率以第一段为准；不同采样率直接拼接会变调，所以不一致时先重采样。
    """
    if not parts:
        raise ValueError("没有可拼接的音频")
    chunks: list[np.ndarray] = []
    spans: list[list[int]] = []
    rate = 0
    cursor_samples = 0
    for wav, pause_ms in parts:
        samples, sr = read_wav(wav)
        if rate == 0:
            rate = sr
        samples = _resample(samples, sr, rate)
        start = cursor_samples
        cursor_samples += len(samples)
        spans.append([start * 1000 // rate, cursor_samples * 1000 // rate])
        silence = np.zeros(int(rate * pause_ms / 1000), dtype="float32")
        chunks += [samples, silence]
        cursor_samples += len(silence)
    return to_wav_bytes(np.concatenate(chunks), rate), rate, spans


async def _ffmpeg(args: list[str], data: bytes) -> bytes:
    # 参数用列表传，不拼 shell 字符串，防止命令注入；pipe:0/pipe:1 走内存，不落临时文件
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        *args,
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(data)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败：{err.decode(errors='ignore')[:500]}")
    return out


async def loudnorm_wav(wav: bytes) -> bytes:
    """响度标准化到 -16 LUFS（短视频平台常用值），避免句子之间音量忽大忽小。"""
    return await _ffmpeg(["-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "24000", "-ac", "1", "-f", "wav"], wav)


async def wav_to_mp3(wav: bytes) -> bytes:
    return await _ffmpeg(["-ac", "1", "-b:a", "128k", "-f", "mp3"], wav)


async def transcode_upload(data: bytes) -> bytes:
    """用户上传的参考音频：不信任原文件，统一转成 24kHz 单声道 wav。"""
    return await _ffmpeg(["-ac", "1", "-ar", "24000", "-f", "wav"], data)
