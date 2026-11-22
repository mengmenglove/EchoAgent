"""额度：流水、兑换码充值。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import current_user
from app.models import CreditLedger, User
from app.schemas import LedgerOut, RedeemIn, UserOut
from app.services import billing

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/ledger", response_model=list[LedgerOut])
async def ledger(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(CreditLedger).where(CreditLedger.user_id == user.id).order_by(CreditLedger.id.desc()).limit(limit)
    return list((await db.scalars(stmt)).all())


@router.post("/redeem", response_model=UserOut)
async def redeem(body: RedeemIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await billing.redeem(db, user, body.code)
    await db.refresh(user)
    return user
