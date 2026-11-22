"""Claude 客户端单例。

AsyncAnthropic() 不传 api_key 时自动读取环境变量 ANTHROPIC_API_KEY。
SDK 内置重试：429 / 5xx / 网络错误会自动退避重试 max_retries 次。
"""

from functools import lru_cache

from anthropic import AsyncAnthropic


@lru_cache
def get_llm() -> AsyncAnthropic:
    return AsyncAnthropic(max_retries=3, timeout=300)
