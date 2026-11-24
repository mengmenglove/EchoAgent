"""数据库表。字段说明见 docs/DEVELOPMENT_PLAN.md 第 5 节。

为了让测试能用 SQLite 跑，JSON 字段写成 JSON().with_variant(JSONB, "postgresql")：
生产用 Postgres 的 JSONB，测试用 SQLite 的 JSON，代码不用改。
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    TypeDecorator,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")
# SQLite 只有 INTEGER PRIMARY KEY 才会自增
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """带时区的时间。SQLite 不保存时区，读出来补上 UTC；
    否则接口返回的时间没有时区，浏览器会当成本地时间，显示差 8 小时。"""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return value.astimezone(UTC) if value is not None else None

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


def utcnow_col(*, onupdate: bool = False, **kw):
    # 时间戳由 Python 生成（带微秒和时区），而不是数据库的 now()：
    # SQLite 的 now() 只精确到秒，同一秒内创建的任务无法按时间稳定排序，游标分页会出错。
    # server_default 保留，用于直接写 SQL 插入数据的场景。
    return mapped_column(
        UTCDateTime(),
        default=_utcnow,
        server_default=func.now(),
        onupdate=_utcnow if onupdate else None,
        **kw,
    )


class Base(DeclarativeBase):
    # 写入时让数据库把服务端生成的值（created_at / updated_at）一并返回（Postgres 用 RETURNING）。
    # 否则这些字段 flush 后处于"过期"状态，异步模式下访问会触发隐式查询，报 MissingGreenlet。
    __mapper_args__ = {"eager_defaults": True}


class JobStatus(StrEnum):
    queued = "queued"
    writing = "writing"
    needs_input = "needs_input"
    synthesizing = "synthesizing"
    verifying = "verifying"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"


TERMINAL_STATUSES = {JobStatus.succeeded, JobStatus.failed, JobStatus.canceled}


class JobMode(StrEnum):
    script = "script"  # 文案直出
    brief = "brief"  # 需求模式（Agent 写稿）


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    credits_balance: Mapped[int] = mapped_column(default=0)
    # 读音词典：{"iPhone": "爱疯"}，合成前替换
    lexicon: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = utcnow_col()


class Voice(Base):
    __tablename__ = "voices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)  # None=系统音色
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(255), default="")
    tags: Mapped[list] = mapped_column(JSONType, default=list)  # ["沉稳", "男声", "知识科普"]
    language: Mapped[str] = mapped_column(String(16), default="zh")
    # 参考音频二选一：系统音色用 F5 机器上的本地路径；用户上传的音色存在对象存储里
    ref_audio_path: Mapped[str | None] = mapped_column(String(512))
    ref_audio_key: Mapped[str | None] = mapped_column(String(512))
    ref_text: Mapped[str] = mapped_column(Text)  # 参考音频里念的原文，必须逐字一致
    consent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())  # 用户声明有权使用该声音
    # 软删除：历史任务还引用着这个音色，不能真删
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = utcnow_col()


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )  # "改一句重新生成"的来源
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.queued, index=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    input_text: Mapped[str] = mapped_column(Text)  # 用户原始输入：文案或需求
    # 分段文案：[{"text": "...", "pause_ms": 400}]，文案模式由分句器生成，需求模式由 Agent 生成
    script: Mapped[list | None] = mapped_column(JSONType)
    voice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voices.id"))
    speed: Mapped[float] = mapped_column(default=1.0)
    target_seconds: Mapped[int | None]
    audio_key: Mapped[str | None] = mapped_column(String(512))  # mp3
    wav_key: Mapped[str | None] = mapped_column(String(512))
    srt_key: Mapped[str | None] = mapped_column(String(512))
    vtt_key: Mapped[str | None] = mapped_column(String(512))
    duration_ms: Mapped[int | None]
    spans: Mapped[list | None] = mapped_column(JSONType)  # 每段 [start_ms, end_ms]，前端高亮用
    verify_report: Mapped[list | None] = mapped_column(JSONType)
    error: Mapped[str | None] = mapped_column(Text)
    # Agent 完整对话，只追加不修改；追问时暂停，回答后从这里继续
    agent_messages: Mapped[list | None] = mapped_column(JSONType)
    # 追问时暂存：{"tool_use_id": ..., "questions": [...], "results": [本轮其他工具结果]}
    pending_input: Mapped[dict | None] = mapped_column(JSONType)
    enqueue_count: Mapped[int] = mapped_column(default=0)  # 用于生成 arq 的 job id
    credits_held: Mapped[int] = mapped_column(default=0)
    credits_charged: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = utcnow_col(index=True)
    updated_at: Mapped[datetime] = utcnow_col(onupdate=True)

    # passive_deletes：删除任务时交给数据库的 ON DELETE CASCADE 清理事件，ORM 不逐条加载
    events: Mapped[list["JobEvent"]] = relationship(
        back_populates="job", order_by="JobEvent.id", cascade="all, delete-orphan", passive_deletes=True
    )


class JobEvent(Base):
    """进度事件。id 全局自增，直接作为 SSE 的 event id，断线重连按 id 续传。"""

    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = utcnow_col()

    job: Mapped[Job] = relationship(back_populates="events")


class LLMUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cache_read_tokens: Mapped[int] = mapped_column(default=0)
    cache_write_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    created_at: Mapped[datetime] = utcnow_col()


class CreditLedger(Base):
    """额度流水：只追加，不修改。余额 = 该用户所有 delta 之和。"""

    __tablename__ = "credit_ledger"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    delta: Mapped[int]
    reason: Mapped[str] = mapped_column(String(16))  # signup | topup | hold | release | charge
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = utcnow_col()


class RedeemCode(Base):
    __tablename__ = "redeem_codes"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    credits: Mapped[int]
    used_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = utcnow_col()


class ChatSession(Base):
    """一段对话。"""

    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(64), default="新对话")
    voice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voices.id"))
    created_at: Mapped[datetime] = utcnow_col(index=True)
    updated_at: Mapped[datetime] = utcnow_col(onupdate=True)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", order_by="ChatMessage.id", cascade="all, delete-orphan", passive_deletes=True
    )


class ChatMessage(Base):
    """一条消息。assistant 的消息合成语音后，audio_key 指向 wav 文件。"""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    audio_key: Mapped[str | None] = mapped_column(String(512))
    audio_ms: Mapped[int | None]
    created_at: Mapped[datetime] = utcnow_col()

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class TTSCache(Base):
    """合成缓存：同样的文本 + 音色 + 语速 + 模型，只合成一次。"""

    __tablename__ = "tts_cache"

    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    audio_key: Mapped[str] = mapped_column(String(512))
    duration_ms: Mapped[int]
    sample_rate: Mapped[int]
    created_at: Mapped[datetime] = utcnow_col()
