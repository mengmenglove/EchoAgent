"""应用配置：全部来自环境变量或 server/.env，见 .env.example。"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=SERVER_DIR / ".env", extra="ignore")

    env: str = "dev"  # dev | prod
    database_url: str = "postgresql+asyncpg://echo:echo@127.0.0.1:5432/echo"
    # 留空 = 不用 Redis：任务在 API 进程里执行，进度从数据库读。上线要多进程时再配 redis://127.0.0.1:6379/0
    redis_url: str = ""
    cors_origins: list[str] = []

    # 认证。没有默认值：没配置就启动失败，避免用弱密钥上线。
    jwt_secret: str = Field(min_length=32)
    jwt_expire_days: int = 7
    cookie_name: str = "echo_session"

    # 大模型。ANTHROPIC_API_KEY 由 SDK 直接从环境变量读取。
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"  # low | medium | high | xhigh | max
    llm_max_turns: int = 8
    # 服务端 fallback（beta）。经过不认识该参数的代理网关时会报 400，可以关掉
    llm_fallbacks: bool = True

    # 聊天（本地 Ollama）。聊天功能只用它，不需要 Claude
    ollama_base_url: str = "http://127.0.0.1:11434"
    chat_model: str = "qwen3.5:4b"
    chat_history_turns: int = 10  # 每次只带最近 10 轮对话，控制速度和显存
    chat_max_reply_chars: int = 300  # 回复要合成语音，太长会等很久

    # 语音合成
    tts_provider: str = "f5"  # f5 | mock
    f5_base_url: str = "http://127.0.0.1:8765"
    f5_home: Path = Path.home() / "Documents/LLMWorkSpace/F5-TTS"
    tts_model_version: str = "F5TTS_v1_Base"  # 参与合成缓存的哈希，换模型后旧缓存自动失效

    # 存储
    storage_backend: str = "local"  # local | s3
    storage_dir: Path = SERVER_DIR / "storage"
    cache_dir: Path = SERVER_DIR / "storage" / "_cache"
    s3_bucket: str = ""
    s3_endpoint_url: str | None = None
    s3_region: str | None = None

    # 计费与限流
    signup_credits: int = 300
    brief_fee_credits: int = 10
    max_active_jobs: int = 2
    daily_job_limit: int = 50

    # 质检（M4，默认关闭；开启需要安装 ASR 依赖，见文档）
    verify_enabled: bool = False
    verify_cer_threshold: float = 0.15

    # Worker
    job_timeout_seconds: int = 15 * 60
    job_max_tries: int = 2

    @field_validator("database_url")
    @classmethod
    def _anchor_sqlite(cls, v: str) -> str:
        # SQLite 相对路径固定从 server/ 算起，不管从哪个目录启动都是同一个库
        prefix = "sqlite+aiosqlite:///./"
        return f"sqlite+aiosqlite:///{SERVER_DIR}/{v.removeprefix(prefix)}" if v.startswith(prefix) else v

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
