"""语音聊天：假的 Ollama（respx 拦截 HTTP）+ MockProvider，不需要真模型和 F5。"""

import asyncio
import json

import httpx
import pytest
import respx

from app.config import settings
from app.llm.ollama import OllamaChat
from tests.conftest import register

OLLAMA = "http://ollama.test"


def ndjson(*chunks: str) -> bytes:
    lines = [{"message": {"role": "assistant", "content": c}, "done": False} for c in chunks]
    lines.append({"message": {"role": "assistant", "content": ""}, "done": True})
    return "\n".join(json.dumps(x) for x in lines).encode()


@pytest.fixture
async def chat_app(app):
    http = httpx.AsyncClient()
    app.state.chat_llm = OllamaChat(http, OLLAMA, "qwen3.5:4b")
    yield app
    await http.aclose()


def events(body: str) -> list[tuple[str, dict]]:
    out, ev = [], None
    for line in body.splitlines():
        if line.startswith("event: "):
            ev = line[7:]
        elif line.startswith("data: "):
            out.append((ev, json.loads(line[6:])))
    return out


async def new_session(client) -> str:
    r = await client.post("/api/chat/sessions", json={})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@respx.mock
async def test_chat_reply_then_speech(chat_app, user_client, system_voice, tts):
    route = respx.post(f"{OLLAMA}/api/chat").mock(
        return_value=httpx.Response(200, content=ndjson("Hi there! ", "Nice to meet you. ", "How are you?"))
    )
    sid = await new_session(user_client)
    r = await user_client.post(f"/api/chat/sessions/{sid}/messages", json={"text": "Hello, my name is Lee."})
    ev = events(r.text)
    types = [t for t, _ in ev]
    assert types[0] == "user_saved" and types[-1] == "done"
    assert types.count("delta") == 3 and "text_done" in types and "audio" in types
    reply = dict(ev)["text_done"]["text"]
    assert reply == "Hi there! Nice to meet you. How are you?"

    # 发给 Ollama 的请求：关掉思考、带上系统提示和用户这句话
    sent = json.loads(route.calls[0].request.content)
    assert sent["think"] is False and sent["model"] == "qwen3.5:4b" and sent["stream"] is True
    assert sent["messages"][0]["role"] == "system"
    assert sent["messages"][-1] == {"role": "user", "content": "Hello, my name is Lee."}

    # 英文按句合成，不被套上中文规则
    assert tts.calls == ["Hi there!", "Nice to meet you.", "How are you?"]

    msgs = (await user_client.get(f"/api/chat/sessions/{sid}/messages")).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["has_audio"] and msgs[1]["audio_ms"] > 0
    audio = await user_client.get(f"/api/chat/sessions/{sid}/messages/{msgs[1]['id']}/audio")
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF"

    sessions = (await user_client.get("/api/chat/sessions")).json()
    assert sessions[0]["title"] == "Hello, my name is Lee."


@respx.mock
async def test_history_is_sent_and_capped(chat_app, user_client, system_voice, monkeypatch):
    monkeypatch.setattr(settings, "chat_history_turns", 2)
    route = respx.post(f"{OLLAMA}/api/chat").mock(side_effect=lambda req: httpx.Response(200, content=ndjson("ok.")))
    sid = await new_session(user_client)
    for i in range(4):
        await user_client.post(f"/api/chat/sessions/{sid}/messages", json={"text": f"msg {i}", "speak": False})
    last = json.loads(route.calls[-1].request.content)["messages"]
    # system + 最近 2 轮（4 条）+ 本轮用户消息
    assert [m["content"] for m in last[1:]] == ["msg 1", "ok.", "msg 2", "ok.", "msg 3"]


@respx.mock
async def test_chinese_reply_normalized(chat_app, user_client, system_voice, tts):
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=httpx.Response(200, content=ndjson("这个只要99元。")))
    sid = await new_session(user_client)
    await user_client.post(f"/api/chat/sessions/{sid}/messages", json={"text": "多少钱"})
    assert tts.calls == ["这个只要九十九元。"]


@respx.mock
async def test_same_reply_hits_tts_cache(chat_app, user_client, system_voice, tts):
    respx.post(f"{OLLAMA}/api/chat").mock(side_effect=lambda req: httpx.Response(200, content=ndjson("Great job!")))
    sid = await new_session(user_client)
    for _ in range(2):
        await user_client.post(f"/api/chat/sessions/{sid}/messages", json={"text": "hi"})
    assert tts.calls == ["Great job!"]


@respx.mock
async def test_ollama_down_reports_error(chat_app, user_client, system_voice):
    respx.post(f"{OLLAMA}/api/chat").mock(side_effect=httpx.ConnectError("refused"))
    sid = await new_session(user_client)
    ev = events((await user_client.post(f"/api/chat/sessions/{sid}/messages", json={"text": "hi"})).text)
    assert ev[-1][0] == "error" and "make ollama" in ev[-1][1]["message"]
    msgs = (await user_client.get(f"/api/chat/sessions/{sid}/messages")).json()
    assert [m["role"] for m in msgs] == ["user"]  # 用户的话保留了，没有空回复


@respx.mock
async def test_model_not_pulled(chat_app, user_client, system_voice):
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=httpx.Response(404, json={"error": "model not found"}))
    sid = await new_session(user_client)
    ev = events((await user_client.post(f"/api/chat/sessions/{sid}/messages", json={"text": "hi"})).text)
    assert "ollama pull qwen3.5:4b" in ev[-1][1]["message"]


@respx.mock
async def test_tts_failure_keeps_text(chat_app, user_client, system_voice, deps, monkeypatch):
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=httpx.Response(200, content=ndjson("Hello.")))

    async def boom(*_):
        raise RuntimeError("F5 坏了")

    monkeypatch.setattr(deps.tts, "synthesize", boom)
    sid = await new_session(user_client)
    ev = events((await user_client.post(f"/api/chat/sessions/{sid}/messages", json={"text": "hi"})).text)
    types = [t for t, _ in ev]
    assert "text_done" in types and "audio_error" in types and types[-1] == "done"


async def test_cannot_access_others_session(app, chat_app, user_client, system_voice):
    sid = await new_session(user_client)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as other:
        await register(other, "b@example.com")
        assert (await other.get(f"/api/chat/sessions/{sid}/messages")).status_code == 404
        assert (await other.post(f"/api/chat/sessions/{sid}/messages", json={"text": "hi"})).status_code == 404
        assert (await other.delete(f"/api/chat/sessions/{sid}")).status_code == 404


async def test_delete_session(chat_app, user_client, system_voice):
    sid = await new_session(user_client)
    assert (await user_client.delete(f"/api/chat/sessions/{sid}")).status_code == 204
    assert (await user_client.get("/api/chat/sessions")).json() == []


@respx.mock
async def test_ollama_health_checks_model_pulled():
    async with httpx.AsyncClient() as http:
        llm = OllamaChat(http, OLLAMA, "qwen3.5:4b")
        respx.get(f"{OLLAMA}/api/tags").mock(return_value=httpx.Response(200, json={"models": [{"name": "other"}]}))
        assert await llm.health() is False
        respx.get(f"{OLLAMA}/api/tags").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})
        )
        assert await llm.health() is True


@respx.mock
async def test_language_follows_latest_message(chat_app, user_client, system_voice):
    route = respx.post(f"{OLLAMA}/api/chat").mock(side_effect=lambda req: httpx.Response(200, content=ndjson("ok.")))
    sid = await new_session(user_client)
    await user_client.post(f"/api/chat/sessions/{sid}/messages", json={"text": "Hello there", "speak": False})
    await user_client.post(f"/api/chat/sessions/{sid}/messages", json={"text": "你好，聊聊天", "speak": False})
    first, second = (json.loads(c.request.content)["messages"][0]["content"] for c in route.calls)
    assert "Reply in English" in first and "Reply in Chinese" in second


@respx.mock
async def test_progress_and_heartbeat_during_slow_tts(chat_app, user_client, system_voice, deps, monkeypatch):
    import app.services.chat as chat_mod

    monkeypatch.setattr(chat_mod, "PING_SECONDS", 0.05)
    respx.post(f"{OLLAMA}/api/chat").mock(
        return_value=httpx.Response(200, content=ndjson("This is the first one. This is the second one."))
    )
    real = deps.tts.synthesize

    async def slow(*a):
        await asyncio.sleep(0.3)
        return await real(*a)

    monkeypatch.setattr(deps.tts, "synthesize", slow)
    sid = await new_session(user_client)
    types = [
        t for t, _ in events((await user_client.post(f"/api/chat/sessions/{sid}/messages", json={"text": "hi"})).text)
    ]
    assert "ping" in types
    assert [t for t in types if t in ("audio_progress", "audio")] == ["audio_progress", "audio_progress", "audio"]


@respx.mock
async def test_audio_saved_even_if_client_disconnects(chat_app, system_voice, deps, tts, monkeypatch):
    """模拟前端在语音合成期间断开：生成器被关掉，语音仍然合成完并存库。"""
    from app.db import SessionLocal
    from app.models import ChatMessage, ChatSession, User
    from app.services import chat as chat_service

    respx.post(f"{OLLAMA}/api/chat").mock(return_value=httpx.Response(200, content=ndjson("Hello there.")))
    gate = asyncio.Event()
    real = deps.tts.synthesize

    async def wait_gate(*a):
        await gate.wait()
        return await real(*a)

    monkeypatch.setattr(deps.tts, "synthesize", wait_gate)
    async with SessionLocal() as db:
        user = User(email="d@x.com", password_hash="x")
        db.add(user)
        await db.flush()
        s = ChatSession(user_id=user.id, voice_id=system_voice.id)
        db.add(s)
        await db.commit()
        gen = chat_service.send(db, s, "hi", llm=chat_app.state.chat_llm, tts=deps.tts, storage=deps.storage)
        async for ev, _ in gen:
            if ev == "text_done":
                break
        await gen.aclose()  # 相当于浏览器断开
    gate.set()
    async with asyncio.timeout(5):
        while True:
            async with SessionLocal() as db:
                msg = (await db.scalars(chat_service.select(ChatMessage).where(ChatMessage.role == "assistant"))).one()
                if msg.audio_key:
                    break
            await asyncio.sleep(0.05)
    assert msg.audio_ms and msg.audio_ms > 0
