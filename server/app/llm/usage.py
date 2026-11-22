"""记录每一次模型调用的 Token 用量和成本。成本控制、定价都建立在这张表上。"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LLMUsage

# 美元 / 百万 Token：(输入, 输出, 缓存读, 缓存写)
# 输入/输出价来自官方价目表；缓存读写价按常见比例填写，上线前请对照官方定价页核对。
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}
DEFAULT_PRICE = PRICES["claude-opus-5-5"]


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int) -> Decimal:
    p_in, p_out, p_cr, p_cw = PRICES.get(model, DEFAULT_PRICE)
    total = input_tokens * p_in + output_tokens * p_out + cache_read * p_cr + cache_write * p_cw
    return Decimal(str(round(total / 1_000_000, 6)))


async def record_usage(db: AsyncSession, job_id: uuid.UUID | None, resp) -> LLMUsage:
    """resp 是 SDK 返回的 Message。思考过程的 Token 也计入 output_tokens。"""
    u = resp.usage
    cache_read = u.cache_read_input_tokens or 0
    cache_write = u.cache_creation_input_tokens or 0
    row = LLMUsage(
        job_id=job_id,
        model=resp.model,  # 触发了 fallback 时，这里是实际服务的模型
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        cost_usd=cost_usd(resp.model, u.input_tokens, u.output_tokens, cache_read, cache_write),
    )
    db.add(row)
    await db.flush()
    return row
