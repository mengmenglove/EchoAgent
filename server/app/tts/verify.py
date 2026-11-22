"""质检（M4）：把合成的每句音频用 ASR 转回文字，和规整后的文本比对字错误率（CER）。

默认关闭（VERIFY_ENABLED=false）。开启前需要安装一个 ASR 后端，目前实现了 mlx-whisper：
    uv add mlx-whisper
它在 Apple Silicon 上用 GPU 跑 Whisper。中文效果更好的 FunASR(Paraformer) 可以照着 ASRProvider 再写一个。
"""

import asyncio
import re
import tempfile
from typing import Protocol


class ASRProvider(Protocol):
    async def transcribe(self, wav: bytes) -> str: ...


class MlxWhisperASR:
    def __init__(self, model: str = "mlx-community/whisper-large-v3-turbo"):
        import mlx_whisper  # 可选依赖，没装会在开启质检时报错

        self._mlx = mlx_whisper
        self.model = model

    async def transcribe(self, wav: bytes) -> str:
        def _run() -> str:
            with tempfile.NamedTemporaryFile(suffix=".wav") as f:
                f.write(wav)
                f.flush()
                out = self._mlx.transcribe(f.name, path_or_hf_repo=self.model, language="zh")
                return out.get("text", "")

        return await asyncio.to_thread(_run)  # 推理是 CPU/GPU 密集的同步调用，放进线程


_STRIP = re.compile(r"[\s，。！？、；：,.!?;:\"'“”‘’（）()\-—…]")


def cer(ref: str, hyp: str) -> float:
    """字错误率 = 编辑距离 / 参考文本长度（忽略标点和空格）。"""
    r, h = _STRIP.sub("", ref), _STRIP.sub("", hyp)
    if not r:
        return 0.0
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hc in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc))
        prev = cur
    return prev[-1] / len(r)


def make_asr() -> ASRProvider:
    return MlxWhisperASR()
