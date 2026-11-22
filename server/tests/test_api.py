"""API 测试：鉴权、越权、参数校验、额度、完整的文案直出链路。"""

from httpx import ASGITransport, AsyncClient

from app.config import settings
from tests.conftest import register, run_worker

SCRIPT = "今天给大家介绍一款咖啡机。它只要三分钟就能做好一杯拿铁！价格只要299元，你心动了吗？"


async def test_register_login_me(client):
    data = await register(client)
    assert data["user"]["credits_balance"] == settings.signup_credits
    assert data["token"]

    me = await client.get("/api/me")
    assert me.status_code == 200 and me.json()["email"] == "a@example.com"

    await client.post("/api/auth/logout")
    client.cookies.clear()
    assert (await client.get("/api/me")).status_code == 401

    bad = await client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong-pass"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "unauthorized"

    ok = await client.post("/api/auth/login", json={"email": "A@Example.com", "password": "password123"})
    assert ok.status_code == 200


async def test_bearer_token_auth(client):
    token = (await register(client))["token"]
    client.cookies.clear()
    r = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


async def test_duplicate_email(client):
    await register(client)
    r = await client.post("/api/auth/register", json={"email": "a@example.com", "password": "password123"})
    assert r.status_code == 409


async def test_validation_error_format(user_client):
    r = await user_client.post("/api/jobs", json={"mode": "script", "text": "你好"})
    assert r.status_code == 422
    assert r.json()["error"]["message"] == "文案直出模式必须指定音色"


async def test_script_job_end_to_end(user_client, system_voice, queue, deps, tts):
    r = await user_client.post("/api/jobs", json={"mode": "script", "text": SCRIPT, "voice_id": str(system_voice.id)})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "queued"
    assert len(job["script"]) == 3
    held = job["credits_held"]
    assert held > 0
    me = (await user_client.get("/api/me")).json()
    assert me["credits_balance"] == settings.signup_credits - held

    await run_worker(queue, deps)

    job = (await user_client.get(f"/api/jobs/{job['id']}")).json()
    assert job["status"] == "succeeded", job["error"]
    assert job["has_audio"] and job["duration_ms"] > 0
    assert len(job["spans"]) == 3
    assert job["credits_held"] == 0 and 0 < job["credits_charged"] <= held
    # 合成的是规整后的文本（数字变成了汉字）
    assert any("二百九十九元" in t for t in tts.calls)

    me = (await user_client.get("/api/me")).json()
    assert me["credits_balance"] == settings.signup_credits - job["credits_charged"]

    mp3 = await user_client.get(f"/api/jobs/{job['id']}/file?format=mp3")
    assert mp3.status_code == 200 and mp3.headers["content-type"] == "audio/mpeg"
    # 支持 Range：浏览器拖动进度条靠它
    part = await user_client.get(f"/api/jobs/{job['id']}/file?format=mp3", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100

    srt = await user_client.get(f"/api/jobs/{job['id']}/file?format=srt&download=true")
    assert "299元" in srt.text  # 字幕显示原文
    assert "attachment" in srt.headers["content-disposition"]

    ledger = (await user_client.get("/api/billing/ledger")).json()
    assert [x["reason"] for x in ledger] == ["charge", "release", "hold", "signup"]


async def test_events_replay(user_client, system_voice, queue, deps):
    job = (
        await user_client.post("/api/jobs", json={"mode": "script", "text": SCRIPT, "voice_id": str(system_voice.id)})
    ).json()
    await run_worker(queue, deps)

    r = await user_client.get(f"/api/jobs/{job['id']}/events")
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert "tts_segment_done" in body and '"type": "succeeded"' in body

    # 断线续传：带上 Last-Event-ID，只返回之后的事件
    ids = [int(line[4:]) for line in body.splitlines() if line.startswith("id: ")]
    r2 = await user_client.get(f"/api/jobs/{job['id']}/events", headers={"Last-Event-ID": str(ids[-2])})
    assert [int(line[4:]) for line in r2.text.splitlines() if line.startswith("id: ")] == [ids[-1]]


async def test_tts_cache_on_revise(user_client, system_voice, queue, deps, tts):
    job = (
        await user_client.post("/api/jobs", json={"mode": "script", "text": SCRIPT, "voice_id": str(system_voice.id)})
    ).json()
    await run_worker(queue, deps)
    assert len(tts.calls) == 3

    job = (await user_client.get(f"/api/jobs/{job['id']}")).json()
    segments = job["script"]
    segments[1] = {"text": "它只要两分钟就能做好一杯拿铁！", "pause_ms": 400}
    r = await user_client.post(f"/api/jobs/{job['id']}/revise", json={"segments": segments})
    assert r.status_code == 202, r.text
    await run_worker(queue, deps)

    assert len(tts.calls) == 4  # 只重新合成了改动的那一句
    child = (await user_client.get(f"/api/jobs/{r.json()['id']}")).json()
    assert child["status"] == "succeeded" and child["parent_id"] == job["id"]


async def test_cannot_access_others_job(app, user_client, system_voice):
    job = (
        await user_client.post("/api/jobs", json={"mode": "script", "text": SCRIPT, "voice_id": str(system_voice.id)})
    ).json()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        await register(other, "b@example.com")
        for path in ["", "/events", "/file", "/cancel"]:
            method = other.post if path == "/cancel" else other.get
            r = await method(f"/api/jobs/{job['id']}{path}")
            assert r.status_code == 404, path
        assert (await other.get("/api/jobs")).json()["items"] == []


async def test_cancel_releases_credits(user_client, system_voice, queue, deps):
    job = (
        await user_client.post("/api/jobs", json={"mode": "script", "text": SCRIPT, "voice_id": str(system_voice.id)})
    ).json()
    r = await user_client.post(f"/api/jobs/{job['id']}/cancel")
    assert r.json()["status"] == "canceled"
    assert (await user_client.get("/api/me")).json()["credits_balance"] == settings.signup_credits

    await run_worker(queue, deps)  # Worker 拿到已取消的任务，应该直接跳过
    assert (await user_client.get(f"/api/jobs/{job['id']}")).json()["status"] == "canceled"


async def test_insufficient_credits(user_client, system_voice, monkeypatch):
    monkeypatch.setattr(settings, "max_active_jobs", 100)
    long_text = "这是一段用来消耗额度的很长的测试文案内容。" * 120
    r = await user_client.post(
        "/api/jobs", json={"mode": "script", "text": long_text[:5000], "voice_id": str(system_voice.id)}
    )
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "insufficient_credits"
    assert (await user_client.get("/api/me")).json()["credits_balance"] == settings.signup_credits


async def test_active_job_limit(user_client, system_voice):
    body = {"mode": "script", "text": "第一条测试文案内容。", "voice_id": str(system_voice.id)}
    for _ in range(settings.max_active_jobs):
        assert (await user_client.post("/api/jobs", json=body)).status_code == 202
    r = await user_client.post("/api/jobs", json=body)
    assert r.status_code == 429


async def test_tts_failure_marks_failed_and_refunds(user_client, system_voice, queue, deps, monkeypatch):
    async def boom(*_a, **_k):
        raise ValueError("合成器坏了")

    monkeypatch.setattr(deps.tts, "synthesize", boom)
    job = (
        await user_client.post("/api/jobs", json={"mode": "script", "text": SCRIPT, "voice_id": str(system_voice.id)})
    ).json()
    await run_worker(queue, deps)
    job = (await user_client.get(f"/api/jobs/{job['id']}")).json()
    assert job["status"] == "failed" and "合成器坏了" in job["error"]
    assert (await user_client.get("/api/me")).json()["credits_balance"] == settings.signup_credits


async def test_delete_and_pagination(user_client, system_voice, queue, deps, monkeypatch):
    monkeypatch.setattr(settings, "max_active_jobs", 100)
    ids = []
    for i in range(5):
        body = {"mode": "script", "text": f"第{i}条测试文案。", "voice_id": str(system_voice.id)}
        ids.append((await user_client.post("/api/jobs", json=body)).json()["id"])
    await run_worker(queue, deps)

    page1 = (await user_client.get("/api/jobs?limit=2")).json()
    page2 = (await user_client.get(f"/api/jobs?limit=2&cursor={page1['next_cursor']}")).json()
    page3 = (await user_client.get(f"/api/jobs?limit=2&cursor={page2['next_cursor']}")).json()
    seen = [j["id"] for j in page1["items"] + page2["items"] + page3["items"]]
    assert sorted(seen) == sorted(ids) and len(set(seen)) == 5
    assert page3["next_cursor"] is None

    assert (await user_client.delete(f"/api/jobs/{ids[0]}")).status_code == 204
    assert (await user_client.get(f"/api/jobs/{ids[0]}")).status_code == 404


async def test_redeem_code(user_client):
    from app.db import SessionLocal
    from app.models import RedeemCode

    async with SessionLocal() as db:
        db.add(RedeemCode(code="TESTCODE1234", credits=100))
        await db.commit()
    r = await user_client.post("/api/billing/redeem", json={"code": "testcode1234"})
    assert r.json()["credits_balance"] == settings.signup_credits + 100
    again = await user_client.post("/api/billing/redeem", json={"code": "TESTCODE1234"})
    assert again.status_code == 400


async def test_lexicon_applied(user_client, system_voice, queue, deps, tts):
    await user_client.put("/api/me/lexicon", json={"entries": {"咖啡机": "咖啡鸡"}})
    await user_client.post("/api/jobs", json={"mode": "script", "text": SCRIPT, "voice_id": str(system_voice.id)})
    await run_worker(queue, deps)
    assert "咖啡鸡" in tts.calls[0]


async def test_health(client):
    r = await client.get("/api/health")
    assert r.json() == {"ok": True, "db": True, "redis": True, "tts": True}
