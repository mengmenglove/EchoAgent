from app.agent.script_check import check_script


def seg(text: str, pause: int = 400) -> dict:
    return {"text": text, "pause_ms": pause}


def test_ok_when_within_tolerance():
    # 42 字 ≈ 10 秒
    r = check_script([seg("一" * 21), seg("二" * 21, 0)], target_seconds=10)
    assert r["estimated_seconds"] == 10.4  # 含 0.4 秒停顿
    assert r["ok"]


def test_too_short_gives_advice():
    r = check_script([seg("太短了", 0)], target_seconds=30)
    assert not r["ok"]
    assert "建议总字数调整到约" in r["problems"][0]


def test_banned_words_and_long_segments():
    r = check_script([seg("这是全网最便宜的第一名产品" + "长" * 40, 0)], target_seconds=12)
    assert set(r["banned_words"]) >= {"第一", "全网最", "最便宜"}
    assert r["long_segments"] == [{"index": 0, "units": 53}]
    assert not r["ok"]


def test_banned_word_case_insensitive():
    assert check_script([seg("销量no.1", 0)], target_seconds=2)["banned_words"] == ["NO.1", "No.1"]
