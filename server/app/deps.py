"""FastAPI 依赖：路由函数通过 Depends(...) 声明自己需要什么。"""

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.errors import Unauthorized
from app.models import User
from app.security import decode_token


def _token_from_request(request: Request) -> str | None:
    # 浏览器走 httpOnly Cookie；iOS 等客户端走 Authorization 头
    if token := request.cookies.get(settings.cookie_name):
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = _token_from_request(request)
    if not token:
        raise Unauthorized("未登录")
    user_id = decode_token(token)
    if user_id is None:
        raise Unauthorized("登录已过期，请重新登录")
    user = await db.get(User, user_id)
    if user is None:
        raise Unauthorized("用户不存在")
    return user
