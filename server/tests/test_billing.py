"""额度并发测试：SQLite（整库写锁）和 Postgres（行锁）上都必须成立。"""

import asyncio
import uuid

from sqlalchemy import func, select

from app.db import SessionLocal
from app.errors import InsufficientCredits
from app.models import CreditLedger, Job, User
from app.services import billing


async def test_concurrent_holds_never_go_negative():
    async with SessionLocal() as db:
        user = User(email="race@example.com", password_hash="x", credits_balance=30)
        db.add(user)
        await db.commit()

    async def try_hold() -> bool:
        async with SessionLocal() as db:
            job = Job(id=uuid.uuid4(), user_id=user.id, mode="script", input_text="x")
            db.add(job)
            await db.flush()
            try:
                await billing.hold(db, job, 10)
                await db.commit()
                return True
            except InsufficientCredits:
                await db.rollback()
                return False

    results = await asyncio.gather(*(try_hold() for _ in range(8)))

    assert sum(results) == 3  # 30 额度只够 3 次
    async with SessionLocal() as db:
        balance = await db.scalar(select(User.credits_balance).where(User.id == user.id))
        ledger_sum = await db.scalar(select(func.sum(CreditLedger.delta)).where(CreditLedger.user_id == user.id))
    assert balance == 0
    assert ledger_sum == -30  # 账本和余额对得上
