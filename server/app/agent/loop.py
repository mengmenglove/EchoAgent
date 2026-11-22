"""Agent 主循环：调模型 → 执行它要求的工具 → 把结果发回去 → 直到它调用 finish。

关键约束（每一条都对应一个真实的坑，详见代码解读文档）：
1. 对话历史只追加、不修改，assistant 的内容（包括 thinking 块）原样存回去；
2. 同一轮的所有 tool_result 放在同一条 user 消息里；
3. 工具参数不合法时返回 is_error 结果让模型自我修正，而不是直接报错退出；
4. 限制最大轮数，防止死循环烧钱；
5. 每次调用都记录用量。
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts import NUDGE_FINISH, SYSTEM_PROMPT, brief_message
from app.agent.tools import TOOLS, AgentContext, AskInput, FinishInput, ToolInputError, run_tool
from app.config import settings
from app.errors import TransientError
from app.llm.usage import record_usage
from app.models import Job

Emit = Callable[[str, dict], Awaitable[None]]


class AgentError(Exception):
    """不可重试的 Agent 错误（模型拒绝、超过轮数、请求本身有问题）。"""


@dataclass
class NeedsInput(Exception):
    """Agent 调用了 ask_user：任务暂停，等用户回答。"""

    tool_use_id: str
    questions: list[str]
    results: list[dict]  # 同一轮里其他工具的结果，等回答后一起发回


def _dump_content(blocks) -> list[dict]:
    # 原样保存模型返回的每一个块（text / thinking / tool_use），下一轮原封不动发回去
    return [b.model_dump(mode="json", exclude_none=True) for b in blocks]


def _summarize(name: str, result) -> str:
    if name == "check_script":
        status = "通过" if result["ok"] else "需修改"
        return f"检查稿件：预计 {result['estimated_seconds']} 秒 / 目标 {result['target_seconds']} 秒，{status}"
    if name == "list_voices":
        return f"查看可用音色（{len(result)} 个）"
    if name == "finish":
        return "定稿完成"
    return name


async def call_model(llm: anthropic.AsyncAnthropic, messages: list[dict]):
    extra: dict = {}
    if settings.llm_fallbacks:
        # 被安全分类器误判拒绝时，服务端自动换模型重试，不需要自己维护模型列表
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    try:
        return await llm.beta.messages.create(
            model=settings.llm_model,
            max_tokens=16000,
            # 自适应思考：模型按难度自己决定想多少；effort 控制整体深度和 Token 消耗
            thinking={"type": "adaptive"},
            output_config={"effort": settings.llm_effort},
            # 缓存断点打在 system 末尾：tools + system 这段固定前缀会被缓存
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=messages,
            **extra,
        )
    except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
        # SDK 已经自动重试过仍失败 → 交给 Worker 稍后整体重试
        raise TransientError(f"模型服务暂时不可用：{e}") from e
    except anthropic.APIStatusError as e:
        # 400 / 401 / 403 等：请求本身有问题，重试没用
        raise AgentError(f"模型请求失败（HTTP {e.status_code}）：{e.message}") from e


async def run_agent(llm: anthropic.AsyncAnthropic, db: AsyncSession, job: Job, emit: Emit) -> FinishInput:
    messages: list[dict] = list(job.agent_messages or [])
    if not messages:
        messages.append(
            {
                "role": "user",
                "content": brief_message(
                    job.input_text, job.target_seconds, str(job.voice_id) if job.voice_id else None, job.speed
                ),
            }
        )
    ctx = AgentContext(db=db, job=job)

    for _turn in range(settings.llm_max_turns):
        resp = await call_model(llm, messages)
        await record_usage(db, job.id, resp)

        if resp.stop_reason == "refusal":
            raise AgentError("这个需求无法处理（被模型的安全策略拒绝），请修改需求后重试")
        if resp.stop_reason in ("max_tokens", "model_context_window_exceeded"):
            raise AgentError("模型输出超出长度上限")

        messages.append({"role": "assistant", "content": _dump_content(resp.content)})

        for block in resp.content:
            if block.type == "text" and block.text.strip():
                await emit("agent_note", {"text": block.text.strip()[:500]})

        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            messages.append({"role": "user", "content": NUDGE_FINISH})
            job.agent_messages = list(messages)
            continue

        results: list[dict] = []
        finished: FinishInput | None = None
        ask: tuple[str, AskInput] | None = None
        for tu in tool_uses:
            try:
                out = await run_tool(tu.name, tu.input, ctx)
            except ToolInputError as e:
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": str(e), "is_error": True})
                await emit("agent_step", {"tool": tu.name, "summary": f"{tu.name} 参数有误，模型将自行修正"})
                continue

            if tu.name == "ask_user":
                ask = (tu.id, out)  # 它的结果要等用户回答，先不放进 results
                continue
            if tu.name == "finish":
                finished = out
                payload = "已收到定稿"
            else:
                payload = json.dumps(out, ensure_ascii=False)
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": payload})
            await emit("agent_step", {"tool": tu.name, "summary": _summarize(tu.name, out)})

        if finished is not None:
            messages.append({"role": "user", "content": results})
            job.agent_messages = list(messages)
            return finished

        if ask is not None:
            job.agent_messages = list(messages)
            raise NeedsInput(tool_use_id=ask[0], questions=ask[1].questions, results=results)

        messages.append({"role": "user", "content": results})
        job.agent_messages = list(messages)  # 每轮都整体赋值，JSON 列才会被识别为已修改

    raise AgentError(f"超过 {settings.llm_max_turns} 轮仍未定稿")
