"""本地大模型客户端（Ollama）。

Ollama 原生接口：POST /api/chat，流式返回一行一个 JSON：
  {"message": {"role": "assistant", "content": "你"}, "done": false}
  ...
  {"message": {...}, "done": true, "eval_count": 42, ...}

为什么不用它的 OpenAI 兼容接口（/v1/chat/completions）：Qwen3.5 默认会先"思考"，
关闭思考的 think=false 参数只有原生接口认，兼容接口会忽略它，聊天会慢很多。
"""

import json
from collections.abc import AsyncIterator

import httpx

from app.errors import TransientError


class OllamaChat:
    def __init__(self, http: httpx.AsyncClient, base_url: str, model: str):
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """逐段产出模型回复的文字。"""
        body = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "think": False,  # 聊天要快，关掉思考
            "keep_alive": "30m",  # 模型在内存里多留一会，下一句不用重新加载
            "options": {"temperature": 0.7, "num_ctx": 8192},
        }
        try:
            async with self.http.stream("POST", f"{self.base_url}/api/chat", json=body, timeout=180) as r:
                if r.status_code == 404:
                    raise TransientError(f"本地没有模型 {self.model}，请先执行：ollama pull {self.model}")
                if r.status_code >= 400:
                    raise TransientError(f"Ollama 返回 {r.status_code}：{(await r.aread())[:200]!r}")
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if err := data.get("error"):
                        raise TransientError(f"Ollama 出错：{err}")
                    if text := data.get("message", {}).get("content"):
                        yield text
                    if data.get("done"):
                        return
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
            raise TransientError(f"连不上 Ollama（{self.base_url}），请先启动：make ollama") from e

    async def health(self) -> bool:
        """服务在、模型也已经下载好才算健康。"""
        try:
            r = await self.http.get(f"{self.base_url}/api/tags", timeout=3)
            names = {m.get("name") for m in r.json().get("models", [])}
            return r.status_code == 200 and self.model in names
        except (httpx.HTTPError, ValueError):
            return False
