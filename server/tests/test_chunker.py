from app.tts.chunker import (
    MAX_CHARS,
    PAUSE_PARAGRAPH,
    PAUSE_SENTENCE,
    chunk_segments,
    chunk_text,
    count_units,
    estimate_seconds,
)


def test_split_sentences_and_last_pause_zero():
    chunks = chunk_text("今天给大家介绍一款咖啡机。它只要三分钟就能做好一杯！你心动了吗？")
    assert [c.text for c in chunks] == ["今天给大家介绍一款咖啡机。", "它只要三分钟就能做好一杯！", "你心动了吗？"]
    assert chunks[0].pause_ms == PAUSE_SENTENCE
    assert chunks[-1].pause_ms == 0


def test_short_sentence_merged_into_previous():
    chunks = chunk_text("这款咖啡机真的很好用。是吧？")
    assert [c.text for c in chunks] == ["这款咖啡机真的很好用。是吧？"]


def test_paragraph_pause():
    chunks = chunk_text("第一段的内容在这里。\n\n第二段的内容在这里。")
    assert chunks[0].pause_ms == PAUSE_PARAGRAPH


def test_long_sentence_split_at_commas():
    sentence = "，".join(["这是一个比较长的分句"] * 10) + "。"
    chunks = chunk_text(sentence)
    assert len(chunks) > 1
    assert all(len(c.text) <= MAX_CHARS for c in chunks)
    assert "".join(c.text for c in chunks) == sentence


def test_chunk_segments_keeps_agent_pauses():
    chunks = chunk_segments([{"text": "第一句话。", "pause_ms": 700}, {"text": "第二句话。", "pause_ms": 300}])
    assert [c.pause_ms for c in chunks] == [700, 0]


def test_count_units_and_estimate():
    assert count_units("买iPhone 15只要5999") == 2 + 1 + 1 + 1 + 1  # 买、只要 + iPhone + 15 + 5999
    assert estimate_seconds("一" * 42) == 10
    assert estimate_seconds("一" * 42, speed=2) == 5


def test_english_sentences():
    assert [c.text for c in chunk_text("Hi there! Nice to meet you. How are you?")] == [
        "Hi there!",
        "Nice to meet you.",
        "How are you?",
    ]
    # 小数点不切；短句并入前一句时补空格
    assert [c.text for c in chunk_text("It costs 3.5 dollars. OK?")] == ["It costs 3.5 dollars. OK?"]
