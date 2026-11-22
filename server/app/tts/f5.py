"""本地 F5-TTS 服务适配器。

F5 服务（~/Documents/LLMWorkSpace/F5-TTS/tts_server.py）接口：
  GET  /health -> 200 ok
  POST /tts  {text, out, ref, ref_text, speed} -> wav 二进制

注意：F5 服务只能监听 127.0.0.1，`ref` 能指向任意本地文件，绝不能暴露到外网。
"""

import asyncio
import uuid

import httpx

from app.errors import TransientError
from app.tts.audio import wav_info
from app.tts.base import SynthResult, VoiceRef


class F5Provider:
    name = "f5-local"
    max_concurrency = 1  # 模型对象是共享的，并发调用不安全

    def __init__(self, http: httpx.AsyncClient, base_url: str):
        self.http = http
        self.base_url = base_url.rstrip("/")
        # 同一进程内串行；跨进程靠 Worker 的 max_jobs=1 保证
        self._lock = asyncio.Lock()

    async def synthesize(self, text: str, voice: VoiceRef, speed: float) -> SynthResult:
        payload = {
            "text": text,
            # 输出文件名永远由我们生成，不透传任何用户输入
            "out": f"echo_{uuid.uuid4().hex}.wav",
            "ref": voice.ref_audio_path,
            "ref_text": voice.ref_text,
            "speed": speed,
        }
        try:
            async with self._lock:
                r = await self.http.post(f"{self.base_url}/tts", json=payload)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
            raise TransientError(f"F5 服务无响应：{e!r}") from e
        if r.status_code >= 500:
            raise TransientError(f"F5 合成失败 HTTP {r.status_code}：{r.text[:200]}")
        r.raise_for_status()
        rate, duration_ms = wav_info(r.content)
        return SynthResult(wav_bytes=r.content, sample_rate=rate, duration_ms=duration_ms)

    async def health(self) -> bool:
        try:
            r = await self.http.get(f"{self.base_url}/health", timeout=3)
            return r.status_code == 200
        except httpx.HTTPError:
            return False
