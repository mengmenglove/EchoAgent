"""FastAPI 应用入口。

启动：uv run uvicorn app.main:app --reload --port 8000
文档：http://127.0.0.1:8000/docs （自动生成，可以直接在页面上调接口）
"""

import logging
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import auth, billing, jobs, voices
from app.config import settings
from app.db import SessionLocal
from app.errors import AppError
from app.services import runner
from app.services.memory_queue import MemoryQueue
from app.services.queue import ArqQueue
from app.services.storage import make_storage
from app.tts.factory import make_tts

log = logging.getLogger("echo.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用级资源在这里创建一次，关闭时释放。测试会直接给 app.state 赋假实现，跳过这里。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    http = runner.make_http()
    app.state.storage = make_storage(settings)
    app.state.tts = make_tts(settings, http)  # 只用来做健康检查
    if settings.redis_url:
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        app.state.redis = pool  # ArqRedis 本身就是 redis.asyncio.Redis，可以 publish/subscribe
        app.state.queue = ArqQueue(pool)
        yield
        await pool.aclose()
    else:
        # 不用 Redis：任务就在本进程里执行
        app.state.redis = None
        app.state.queue = MemoryQueue(runner.build_deps(http, None))
        await app.state.queue.start()
        yield
        await app.state.queue.stop()
    await http.aclose()


def create_app(*, use_lifespan: bool = True) -> FastAPI:
    app = FastAPI(title="EchoAgent API", version="0.1.0", lifespan=lifespan if use_lifespan else None)

    if settings.cors_origins:
        # 开发时前端走 Next.js 的 rewrites（同源），一般用不到；iOS/其他域名直连时才需要
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(x) for x in first.get("loc", [])[1:])
        msg = first.get("msg", "参数错误").removeprefix("Value error, ")
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": f"{field}: {msg}" if field else msg}},
        )

    @app.get("/api/health", tags=["meta"])
    async def health(request: Request):
        # redis 为 None 表示没启用，不影响整体状态
        redis = request.app.state.redis
        result: dict[str, bool | None] = {"db": False, "redis": None if redis is None else False, "tts": False}
        try:
            async with SessionLocal() as db:
                await db.execute(text("SELECT 1"))
            result["db"] = True
        except Exception as e:
            log.warning("health db: %s", e)
        try:
            if redis is not None:
                result["redis"] = bool(await redis.ping())
        except Exception as e:
            log.warning("health redis: %s", e)
        try:
            result["tts"] = await request.app.state.tts.health()
        except Exception as e:
            log.warning("health tts: %s", e)
        ok = all(v is not False for v in result.values())
        return JSONResponse(status_code=200 if ok else 503, content={"ok": ok, **result})

    for r in (auth.router, voices.router, jobs.router, billing.router):
        app.include_router(r)
    return app


app = create_app()
