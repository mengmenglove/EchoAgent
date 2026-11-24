"""额度账本。规则（见开发文档 12.4）：

- 1 额度 = 1 秒成品音频；需求模式另加写稿费
- 创建任务：预扣（hold）估算值 × 1.2
- 成功：释放预扣（release），再按实际时长扣费（charge）
- 失败 / 取消：只释放预扣
- 余额修改和写流水必须在同一个事务里，并对 users 行加锁（FOR UPDATE），防止并发扣成负数
- 每个函数都是幂等的：重复调用不会重复扣/退
"""

import math
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_for_update
from app.errors import AppError, InsufficientCredits, NotFound
from app.models import CreditLedger, Job, JobMode, RedeemCode, User
from app.tts.chunker import estimate_seconds


def estimate_credits(mode: str, text: str, target_seconds: int | None, speed: float) -> tuple[float, int]:
    if mode == JobMode.brief:
        seconds = float(target_seconds or 60)
        fee = settings.brief_fee_credits
    else:
        seconds = estimate_seconds(text, speed) + text.count("。") * 0.4
        fee = 0
    return seconds, math.ceil(seconds * 1.2) + fee


def actual_credits(job: Job) -> int:
    fee = settings.brief_fee_credits if job.mode == JobMode.brief else 0
    return math.ceil((job.duration_ms or 0) / 1000) + fee


async def _locked_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    """锁住用户行再改余额。

    用 FOR NO KEY UPDATE 而不是 FOR UPDATE：插入 jobs / credit_ledger 时，外键会对 users 行加
    KEY SHARE 锁；FOR UPDATE 与 KEY SHARE 冲突，两个并发事务会互相等待而死锁（tests/test_billing.py
    能复现）。我们只改余额不改主键，NO KEY UPDATE 足够，它之间仍然互斥，扣费照样串行。
    """
    user = await get_for_update(db, User, user_id, key_share=True)
    if user is None:
        raise NotFound("用户不存在")
    return user


async def grant(db: AsyncSession, user_id: uuid.UUID, amount: int, reason: str, note: str = "") -> None:
    user = await _locked_user(db, user_id)
    user.credits_balance += amount
    db.add(CreditLedger(user_id=user_id, delta=amount, reason=reason, note=note))


async def hold(db: AsyncSession, job: Job, amount: int) -> None:
    """不 commit，由调用方在同一事务里和创建任务一起提交。"""
    user = await _locked_user(db, job.user_id)
    if user.credits_balance < amount:
        raise InsufficientCredits(f"额度不足：需要 {amount}，当前 {user.credits_balance}")
    user.credits_balance -= amount
    job.credits_held = amount
    db.add(CreditLedger(user_id=user.id, delta=-amount, reason="hold", job_id=job.id))


async def release(db: AsyncSession, job: Job, note: str = "") -> None:
    if job.credits_held <= 0:
        return  # 已经释放过
    user = await _locked_user(db, job.user_id)
    user.credits_balance += job.credits_held
    db.add(CreditLedger(user_id=user.id, delta=job.credits_held, reason="release", job_id=job.id, note=note))
    job.credits_held = 0


async def settle(db: AsyncSession, job: Job) -> None:
    """成功后结算。实际费用超过预扣时，最多只扣预扣的额度（多出的部分平台承担）。"""
    if job.credits_held <= 0 or job.credits_charged > 0:
        return
    held = job.credits_held
    charge = min(actual_credits(job), held)
    await release(db, job, note="结算")
    user = await _locked_user(db, job.user_id)
    user.credits_balance -= charge
    db.add(CreditLedger(user_id=user.id, delta=-charge, reason="charge", job_id=job.id))
    job.credits_charged = charge


async def redeem(db: AsyncSession, user: User, code: str) -> int:
    rc = await get_for_update(db, RedeemCode, code.strip().upper())
    if rc is None or rc.used_by is not None:
        raise AppError("兑换码无效或已被使用", code="invalid_code")
    rc.used_by = user.id
    rc.used_at = datetime.now(UTC)
    await grant(db, user.id, rc.credits, "topup", note=f"兑换码 {rc.code}")
    await db.commit()
    return rc.credits


def new_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 去掉了易混淆的 0/O/1/I
    return "".join(secrets.choice(alphabet) for _ in range(12))
