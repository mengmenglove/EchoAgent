"""假的 TTS：按文本长度生成一段柔和的提示音。

用途：没开 F5（或在没有 GPU 的机器上）也能把整条链路跑通、调试前端；测试也用它。
配置 TTS_PROVIDER=mock 启用。
"""

import numpy as np

from app.tts.audio import to_wav_bytes
from app.tts.base import SynthResult, VoiceRef
from app.tts.chunker import estimate_seconds

RATE = 24000


class MockProvider:
    name = "mock"
    max_concurrency = 4

    def __init__(self) -> None:
        self.calls: list[str] = []  # 测试里用来断言合成了哪些句子

    async def synthesize(self, text: str, voice: VoiceRef, speed: float) -> SynthResult:
        self.calls.append(text)
        seconds = max(0.5, estimate_seconds(text, speed))
        t = np.linspace(0, seconds, int(RATE * seconds), endpoint=False)
        tone = 0.1 * np.sin(2 * np.pi * 440 * t) * np.hanning(len(t))
        return SynthResult(to_wav_bytes(tone.astype("float32"), RATE), RATE, int(seconds * 1000))

    async def health(self) -> bool:
        return True
