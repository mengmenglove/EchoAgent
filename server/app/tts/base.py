"""TTS 抽象接口。业务代码只依赖这个协议，不关心背后是 F5、豆包还是 ElevenLabs。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VoiceRef:
    """一次合成所需的音色信息（F5 的音色 = 参考音频 + 它念的原文）。"""

    id: str
    ref_audio_path: str  # 合成机器上可读的本地路径
    ref_text: str


@dataclass(frozen=True)
class SynthResult:
    wav_bytes: bytes
    sample_rate: int
    duration_ms: int


class TTSProvider(Protocol):
    name: str
    max_concurrency: int

    async def synthesize(self, text: str, voice: VoiceRef, speed: float) -> SynthResult: ...

    async def health(self) -> bool: ...
