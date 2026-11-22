"""Agent 的工具：定义（给模型看的 JSON Schema）+ 实现（我们的 Python 代码）。

strict: true 保证模型给出的参数一定符合 schema 的结构和类型；
但数值范围、业务规则（例如音色是否属于该用户）schema 管不了，所以实现里再用 Pydantic 校验一遍，
不合法就作为 is_error 的工具结果返回给模型，让它自己改。
"""

import uuid
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.script_check import check_script
from app.models import Job
from app.services.voices import list_accessible

_SEGMENTS_SCHEMA = {
    "type": "array",
    "description": "口播稿分段，按朗读顺序排列",
    "items": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "这一段要念的话，建议 8~40 字"},
            "pause_ms": {"type": "integer", "description": "这一段念完后的停顿毫秒数，常用 300~800"},
        },
        "required": ["text", "pause_ms"],
        "additionalProperties": False,
    },
}

TOOLS: list[dict] = [
    {
        "name": "check_script",
        "description": "检查口播稿：估算朗读时长、找出超长段落和广告法违禁词。每次写完或修改稿件后都要调用。",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "segments": _SEGMENTS_SCHEMA,
                "target_seconds": {"type": "integer", "description": "目标时长（秒）"},
                "speed": {"type": "number", "description": "计划使用的语速，0.8~1.3"},
            },
            "required": ["segments", "target_seconds", "speed"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_voices",
        "description": "列出可用的配音音色，包括 id、名称、风格标签和说明。选择音色前调用。",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "ask_user",
        "description": "关键信息缺失、无法合理假设时向用户提问。最多 3 个问题。调用后任务会暂停，等用户回答后继续。",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "questions": {"type": "array", "items": {"type": "string"}, "description": "要问用户的问题"}
            },
            "required": ["questions"],
            "additionalProperties": False,
        },
    },
    {
        "name": "finish",
        "description": "提交定稿。稿件必须已经通过 check_script（ok=true）。这是交付稿件的唯一方式。",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "这条口播的标题，20 字以内"},
                "segments": _SEGMENTS_SCHEMA,
                "voice_id": {"type": "string", "description": "list_voices 返回的音色 id"},
                "speed": {"type": "number", "description": "语速，0.8~1.3"},
            },
            "required": ["title", "segments", "voice_id", "speed"],
            "additionalProperties": False,
        },
    },
]


# ---------- 参数校验模型 ----------


class SegmentIn(BaseModel):
    text: str = Field(min_length=1, max_length=120)
    pause_ms: int = Field(ge=0, le=2000)


class CheckInput(BaseModel):
    segments: list[SegmentIn] = Field(min_length=1, max_length=100)
    target_seconds: int = Field(ge=5, le=600)
    speed: float = Field(ge=0.7, le=1.5)


class AskInput(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=3)


class FinishInput(BaseModel):
    title: str = Field(min_length=1, max_length=40)
    segments: list[SegmentIn] = Field(min_length=1, max_length=100)
    voice_id: uuid.UUID
    speed: float = Field(ge=0.7, le=1.5)


class ToolInputError(Exception):
    """参数不合法：作为 is_error=True 的 tool_result 返回给模型。"""


@dataclass
class AgentContext:
    db: AsyncSession
    job: Job


def _validate(model: type[BaseModel], data: dict):
    try:
        return model.model_validate(data)
    except ValidationError as e:
        msgs = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
        raise ToolInputError(f"参数不合法：{msgs}") from e


async def run_tool(name: str, data: dict, ctx: AgentContext):
    """执行工具。返回值会被 JSON 序列化后作为 tool_result 发给模型。"""
    match name:
        case "check_script":
            inp = _validate(CheckInput, data)
            return check_script([s.model_dump() for s in inp.segments], inp.target_seconds, inp.speed)

        case "list_voices":
            voices = await list_accessible(ctx.db, ctx.job.user_id)
            return [
                {
                    "id": str(v.id),
                    "name": v.name,
                    "tags": v.tags,
                    "description": v.description,
                    "language": v.language,
                }
                for v in voices
            ]

        case "ask_user":
            return _validate(AskInput, data)

        case "finish":
            inp = _validate(FinishInput, data)
            allowed = {v.id for v in await list_accessible(ctx.db, ctx.job.user_id)}
            if inp.voice_id not in allowed:
                raise ToolInputError("voice_id 不存在，请先调用 list_voices 获取可用音色")
            if ctx.job.voice_id and inp.voice_id != ctx.job.voice_id:
                raise ToolInputError(f"用户指定了音色 {ctx.job.voice_id}，必须使用它")
            target = ctx.job.target_seconds or 60
            report = check_script([s.model_dump() for s in inp.segments], target, inp.speed)
            if report["banned_words"]:
                raise ToolInputError(f"定稿仍包含违禁词：{'、'.join(report['banned_words'])}，请修改后再提交")
            return inp

        case _:
            raise ToolInputError(f"未知工具：{name}")
