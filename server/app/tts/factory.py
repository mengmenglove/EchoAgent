"""按配置创建 TTS Provider。新增一家厂商：写一个实现 TTSProvider 的类，在这里加一个分支。"""

import httpx

from app.config import Settings
from app.tts.base import TTSProvider
from app.tts.f5 import F5Provider
from app.tts.mock import MockProvider


def make_tts(settings: Settings, http: httpx.AsyncClient) -> TTSProvider:
    match settings.tts_provider:
        case "f5":
            return F5Provider(http, settings.f5_base_url)
        case "mock":
            return MockProvider()
        case other:
            raise ValueError(f"未知的 TTS_PROVIDER：{other}")
