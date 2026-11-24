"""API 的请求 / 响应模型（Pydantic）。前端 web/lib/schemas.ts 与这里一一对应。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class Segment(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    pause_ms: int = Field(default=400, ge=0, le=3000)


# ---------- 用户 ----------


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    credits_balance: int
    created_at: datetime


class AuthOut(BaseModel):
    user: UserOut
    token: str  # iOS 等非浏览器客户端用 Authorization: Bearer <token>


class LexiconIn(BaseModel):
    entries: dict[str, str] = Field(max_length=500)

    @field_validator("entries")
    @classmethod
    def check_entries(cls, v: dict[str, str]) -> dict[str, str]:
        for k, val in v.items():
            if not k.strip() or not val.strip() or len(k) > 50 or len(val) > 50:
                raise ValueError("词条和读音都不能为空，且不超过 50 字")
        return v


# ---------- 音色 ----------


class VoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    tags: list[str]
    language: str
    is_mine: bool = False


# ---------- 任务 ----------


class CreateJobIn(BaseModel):
    mode: Literal["script", "brief"]
    text: str = Field(min_length=1, max_length=5000)  # 文案或需求
    target_seconds: int | None = Field(default=None, ge=5, le=600)
    voice_id: uuid.UUID | None = None  # 需求模式可以不填，让 Agent 选
    speed: float = Field(default=1.0, ge=0.7, le=1.5)

    @model_validator(mode="after")
    def check(self):
        if self.mode == "script" and self.voice_id is None:
            raise ValueError("文案直出模式必须指定音色")
        return self


class ReviseJobIn(BaseModel):
    """改稿重新生成：给出完整的新分段，没改的句子会命中合成缓存。"""

    segments: list[Segment] = Field(min_length=1, max_length=200)
    voice_id: uuid.UUID | None = None
    speed: float | None = Field(default=None, ge=0.7, le=1.5)


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None
    mode: str
    status: str
    title: str
    input_text: str
    script: list[Segment] | None
    voice_id: uuid.UUID | None
    speed: float
    target_seconds: int | None
    duration_ms: int | None
    spans: list[list[int]] | None
    verify_report: list[dict] | None
    error: str | None
    pending_questions: list[str] | None = None
    credits_held: int
    credits_charged: int
    has_audio: bool = False
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_job(cls, job) -> "JobOut":
        out = cls.model_validate(job)
        out.has_audio = bool(job.audio_key)
        if job.pending_input:
            out.pending_questions = job.pending_input.get("questions")
        return out


class JobListOut(BaseModel):
    items: list[JobOut]
    next_cursor: str | None


class EstimateOut(BaseModel):
    estimated_seconds: float
    credits: int


# ---------- 计费 ----------


class LedgerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    delta: int
    reason: str
    job_id: uuid.UUID | None
    note: str
    created_at: datetime


class RedeemIn(BaseModel):
    code: str = Field(min_length=4, max_length=32)


# ---------- 聊天 ----------


class ChatSessionIn(BaseModel):
    voice_id: uuid.UUID | None = None  # 不填就用第一个可用音色


class ChatSessionPatch(BaseModel):
    voice_id: uuid.UUID


class ChatSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    voice_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ChatMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    speak: bool = True  # 是否把回复合成语音


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    audio_ms: int | None
    has_audio: bool = False
    created_at: datetime

    @classmethod
    def from_msg(cls, m) -> "ChatMessageOut":
        out = cls.model_validate(m)
        out.has_audio = bool(m.audio_key)
        return out
