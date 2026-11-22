"""注册、登录、退出、当前用户、读音词典。"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.deps import current_user
from app.errors import Conflict, Unauthorized
from app.models import User
from app.schemas import AuthOut, LexiconIn, LoginIn, RegisterIn, UserOut
from app.security import create_token, hash_password, verify_password
from app.services import billing

router = APIRouter(prefix="/api", tags=["auth"])


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.jwt_expire_days * 86400,
        httponly=True,  # JS 读不到，XSS 偷不走
        samesite="lax",  # 跨站请求不带 Cookie，防 CSRF
        secure=settings.is_prod,  # 生产环境只走 HTTPS
        path="/",
    )


@router.post("/auth/register", response_model=AuthOut, status_code=201)
async def register(body: RegisterIn, resp: Response, db: AsyncSession = Depends(get_db)):
    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as e:
        raise Conflict("该邮箱已注册") from e
    await billing.grant(db, user.id, settings.signup_credits, "signup", note="注册赠送")
    await db.commit()
    token = create_token(user.id)
    _set_cookie(resp, token)
    return AuthOut(user=UserOut.model_validate(user), token=token)


@router.post("/auth/login", response_model=AuthOut)
async def login(body: LoginIn, resp: Response, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    # 用户不存在和密码错误返回同样的提示，不让人探测哪些邮箱注册过
    if user is None or not verify_password(body.password, user.password_hash):
        raise Unauthorized("邮箱或密码错误")
    token = create_token(user.id)
    _set_cookie(resp, token)
    return AuthOut(user=UserOut.model_validate(user), token=token)


@router.post("/auth/logout", status_code=204)
async def logout(resp: Response):
    resp.delete_cookie(settings.cookie_name, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return user


@router.get("/me/lexicon", response_model=dict[str, str])
async def get_lexicon(user: User = Depends(current_user)):
    return user.lexicon or {}


@router.put("/me/lexicon", response_model=dict[str, str])
async def put_lexicon(body: LexiconIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    user.lexicon = dict(body.entries)
    await db.commit()
    return user.lexicon
