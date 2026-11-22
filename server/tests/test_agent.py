"""Agent 循环测试：用 FakeLLM 依次返回预设的响应，不花一分钱测完整的工具调用流程。"""

import uuid

from anthropic.types.beta import BetaMessage

from app.config import settings
from app.db import SessionLocal
from app.models import LLMUsage
from tests.conftest import run_worker

GOOD_SEGMENTS = [
    {"text": "你是不是每天早上都来不及喝咖啡？", "pause_ms": 500},
    {"text": "这台咖啡机三分钟就能做好一杯拿铁，口感顺滑。", "pause_ms": 400},
    {"text": "小巧不占地方，清洗也很方便，上班族用起来特别省心。", "pause_ms": 400},
    {"text": "想要的朋友点击下方链接，早上多睡十分钟。", "pause_ms": 0},
]


def msg(*blocks, stop_reason="tool_use") -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": f"msg_{uuid.uuid4().hex[:8]}",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": list(blocks),
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 2000,
                "cache_creation_input_tokens": 0,
            },
        }
    )


def tool(name: str, inp: dict, id_: str | None = None) -> dict:
    return {"type": "tool_use", "id": id_ or f"toolu_{uuid.uuid4().hex[:8]}", "name": name, "input": inp}


def thinking() -> dict:
    return {"type": "thinking", "thinking": "", "signature": "sig"}


class FakeLLM:
    """模拟 AsyncAnthropic：client.beta.messages.create(...) 依次返回 responses 里的消息。"""

    def __init__(self, responses: list[BetaMessage]):
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.beta = self
        self.messages = self

    async def create(self, **kwargs):
        # 深拷贝请求，便于之后检查"每一轮发给模型的是什么"
        import copy

        self.requests.append(copy.deepcopy(kwargs))
        return self.responses.pop(0)


async def create_brief(client, **extra) -> dict:
    r = await client.post("/api/jobs", json={"mode": "brief", "text": "帮我写一条咖啡机的带货口播", **extra})
    assert r.status_code == 202, r.text
    return r.json()


async def test_agent_happy_path(user_client, system_voice, queue, deps, tts):
    vid = str(system_voice.id)
    deps.llm = FakeLLM(
        [
            msg(thinking(), tool("list_voices", {})),
            msg(tool("check_script", {"segments": GOOD_SEGMENTS, "target_seconds": 15, "speed": 1.0})),
            msg(
                {"type": "text", "text": "稿件已通过检查。"},
                tool("finish", {"title": "咖啡机口播", "segments": GOOD_SEGMENTS, "voice_id": vid, "speed": 1.1}),
            ),
        ]
    )
    job = await create_brief(user_client, target_seconds=15)
    await run_worker(queue, deps)

    job = (await user_client.get(f"/api/jobs/{job['id']}")).json()
    assert job["status"] == "succeeded", job["error"]
    assert job["title"] == "咖啡机口播" and job["speed"] == 1.1 and job["voice_id"] == vid
    assert len(tts.calls) == 4

    reqs = deps.llm.requests
    assert len(reqs) == 3
    first = reqs[0]
    assert first["model"] == settings.llm_model
    assert first["thinking"] == {"type": "adaptive"}
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "<brief>" in first["messages"][0]["content"]
    # 历史只追加：第 3 轮的前缀和第 2 轮完全一致（缓存和 thinking 块都依赖这一点）
    assert reqs[2]["messages"][: len(reqs[1]["messages"])] == reqs[1]["messages"]
    # thinking 块原样传回
    assert reqs[1]["messages"][1]["content"][0]["type"] == "thinking"
    # list_voices 的结果里有这个音色
    assert vid in reqs[1]["messages"][2]["content"][0]["content"]

    async with SessionLocal() as db:
        from sqlalchemy import func, select

        n = await db.scalar(select(func.count()).select_from(LLMUsage))
    assert n == 3

    body = (await user_client.get(f"/api/jobs/{job['id']}/events")).text
    assert "script_ready" in body and "agent_step" in body and "agent_note" in body


async def test_agent_bad_input_is_returned_as_error(user_client, system_voice, queue, deps):
    vid = str(system_voice.id)
    deps.llm = FakeLLM(
        [
            # 语速超出范围 → 返回 is_error，让模型自己改
            msg(tool("finish", {"title": "t", "segments": GOOD_SEGMENTS, "voice_id": vid, "speed": 5.0})),
            msg(tool("finish", {"title": "t", "segments": GOOD_SEGMENTS, "voice_id": vid, "speed": 1.0})),
        ]
    )
    job = await create_brief(user_client)
    await run_worker(queue, deps)
    assert (await user_client.get(f"/api/jobs/{job['id']}")).json()["status"] == "succeeded"
    second_turn_results = deps.llm.requests[1]["messages"][-1]["content"]
    assert second_turn_results[0]["is_error"] is True
    assert "speed" in second_turn_results[0]["content"]


async def test_agent_rejects_unknown_voice_and_banned_words(user_client, system_voice, queue, deps):
    vid = str(system_voice.id)
    bad = [{"text": "全网最便宜的咖啡机，快来买。", "pause_ms": 0}]
    deps.llm = FakeLLM(
        [
            msg(tool("finish", {"title": "t", "segments": GOOD_SEGMENTS, "voice_id": str(uuid.uuid4()), "speed": 1.0})),
            msg(tool("finish", {"title": "t", "segments": bad, "voice_id": vid, "speed": 1.0})),
            msg(tool("finish", {"title": "t", "segments": GOOD_SEGMENTS, "voice_id": vid, "speed": 1.0})),
        ]
    )
    job = await create_brief(user_client)
    await run_worker(queue, deps)
    assert (await user_client.get(f"/api/jobs/{job['id']}")).json()["status"] == "succeeded"
    assert "list_voices" in deps.llm.requests[1]["messages"][-1]["content"][0]["content"]
    assert "违禁词" in deps.llm.requests[2]["messages"][-1]["content"][0]["content"]


async def test_agent_ask_user_pauses_and_resumes(user_client, system_voice, queue, deps):
    vid = str(system_voice.id)
    deps.llm = FakeLLM(
        [
            msg(
                tool("list_voices", {}, "toolu_lv"),
                tool("ask_user", {"questions": ["咖啡机叫什么名字？", "主打什么卖点？"]}, "toolu_ask"),
            ),
            msg(tool("finish", {"title": "t", "segments": GOOD_SEGMENTS, "voice_id": vid, "speed": 1.0})),
        ]
    )
    job = await create_brief(user_client)
    await run_worker(queue, deps)

    paused = (await user_client.get(f"/api/jobs/{job['id']}")).json()
    assert paused["status"] == "needs_input"
    assert paused["pending_questions"] == ["咖啡机叫什么名字？", "主打什么卖点？"]
    assert queue.enqueued == []

    r = await user_client.post(f"/api/jobs/{job['id']}/answer", json={"answer": "叫小咖，主打三分钟出杯"})
    assert r.json()["status"] == "queued"
    assert queue.enqueued == [(job["id"], 2)]  # 第二次入队，arq 的 job id 不同
    await run_worker(queue, deps)

    done = (await user_client.get(f"/api/jobs/{job['id']}")).json()
    assert done["status"] == "succeeded", done["error"]
    # 恢复后的这一轮：list_voices 和 ask_user 两个结果在同一条 user 消息里
    last_user = deps.llm.requests[1]["messages"][-1]
    assert last_user["role"] == "user"
    assert [b["tool_use_id"] for b in last_user["content"]] == ["toolu_lv", "toolu_ask"]
    assert last_user["content"][1]["content"] == "叫小咖，主打三分钟出杯"


async def test_agent_refusal_fails_and_refunds(user_client, queue, deps):
    deps.llm = FakeLLM([msg({"type": "text", "text": ""}, stop_reason="refusal")])
    job = await create_brief(user_client)
    await run_worker(queue, deps)
    job = (await user_client.get(f"/api/jobs/{job['id']}")).json()
    assert job["status"] == "failed" and "安全策略" in job["error"]
    assert (await user_client.get("/api/me")).json()["credits_balance"] == settings.signup_credits


async def test_agent_max_turns(user_client, queue, deps, monkeypatch):
    monkeypatch.setattr(settings, "llm_max_turns", 2)
    deps.llm = FakeLLM([msg(tool("list_voices", {})), msg(tool("list_voices", {}))])
    job = await create_brief(user_client)
    await run_worker(queue, deps)
    job = (await user_client.get(f"/api/jobs/{job['id']}")).json()
    assert job["status"] == "failed" and "2 轮" in job["error"]


async def test_agent_nudged_when_no_tool_call(user_client, system_voice, queue, deps):
    vid = str(system_voice.id)
    deps.llm = FakeLLM(
        [
            msg({"type": "text", "text": "这是稿件……"}, stop_reason="end_turn"),
            msg(tool("finish", {"title": "t", "segments": GOOD_SEGMENTS, "voice_id": vid, "speed": 1.0})),
        ]
    )
    job = await create_brief(user_client)
    await run_worker(queue, deps)
    assert (await user_client.get(f"/api/jobs/{job['id']}")).json()["status"] == "succeeded"
    assert "finish" in deps.llm.requests[1]["messages"][-1]["content"]
