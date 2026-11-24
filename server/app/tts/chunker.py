"""分句：把整篇文案切成适合逐句合成的片段，并给每句配上停顿。

为什么不把整篇直接丢给 F5？
1. 每句可以单独重试、单独缓存（改一句只重合成一句）；
2. 停顿时长由我们精确控制；
3. 能拿到每句的准确起止时间，字幕时间轴才准。
"""

import re
from dataclasses import dataclass

MIN_CHARS = 6  # 短于这个长度的句子合并到前一句
MAX_CHARS = 60  # 长于这个长度的句子在逗号处再切

PAUSE_SENTENCE = 400
PAUSE_COMMA = 200
PAUSE_PARAGRAPH = 700


@dataclass
class Chunk:
    text: str
    pause_ms: int

    def as_dict(self) -> dict:
        return {"text": self.text, "pause_ms": self.pause_ms}


def _split_long(sentence: str, pause_after: int) -> list[Chunk]:
    if len(sentence) <= MAX_CHARS:
        return [Chunk(sentence, pause_after)]
    parts = [p for p in re.split(r"(?<=[，,、：:])", sentence) if p.strip()]
    chunks: list[Chunk] = []
    buf = ""
    for p in parts:
        if buf and len(buf) + len(p) > MAX_CHARS:
            chunks.append(Chunk(buf.strip(), PAUSE_COMMA))
            buf = ""
        buf += p
    if buf.strip():
        chunks.append(Chunk(buf.strip(), pause_after))
    # 没有逗号的超长句只能硬切
    out: list[Chunk] = []
    for c in chunks:
        while len(c.text) > MAX_CHARS * 1.5:
            out.append(Chunk(c.text[:MAX_CHARS], PAUSE_COMMA))
            c = Chunk(c.text[MAX_CHARS:], c.pause_ms)
        out.append(c)
    return out


def chunk_text(text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    for pi, para in enumerate(paragraphs):
        # 中文标点直接切；英文的 . ! ? 后面要跟空格才切，避免把 3.5、e.g. 这类切开
        sentences = [s.strip() for s in re.split(r"(?<=[。！？；…])|(?<=[.!?;])\s+", para) if s and s.strip()]
        for si, sent in enumerate(sentences):
            is_para_end = si == len(sentences) - 1 and pi < len(paragraphs) - 1
            pause = PAUSE_PARAGRAPH if is_para_end else PAUSE_SENTENCE
            for c in _split_long(sent, pause):
                if chunks and len(c.text) < MIN_CHARS and len(chunks[-1].text) + len(c.text) <= MAX_CHARS:
                    # 英文合并要补空格（中文不用）
                    sep = " " if re.search(r"[A-Za-z0-9.!?]$", chunks[-1].text) and c.text[:1].isascii() else ""
                    chunks[-1] = Chunk(chunks[-1].text + sep + c.text, c.pause_ms)
                else:
                    chunks.append(c)
    if chunks:
        chunks[-1].pause_ms = 0
    return chunks


def chunk_segments(segments: list[dict]) -> list[Chunk]:
    """Agent 给出的分段：保留它定的停顿，只把过长的句子再切开。"""
    out: list[Chunk] = []
    for seg in segments:
        text = seg["text"].strip()
        if text:
            out.extend(_split_long(text, int(seg.get("pause_ms", PAUSE_SENTENCE))))
    if out:
        out[-1].pause_ms = 0
    return out


def count_units(text: str) -> int:
    """朗读单位：一个汉字算 1，一个英文单词或一组数字算 1。"""
    cjk = len(re.findall(r"[一-鿿]", text))
    words = len(re.findall(r"[A-Za-z]+|\d+(?:\.\d+)?", text))
    return cjk + words


CHARS_PER_SECOND = 4.2  # 语速 1.0 时中文口播大约每秒 4~4.5 字


def estimate_seconds(text: str, speed: float = 1.0, pauses_ms: int = 0) -> float:
    return count_units(text) / (CHARS_PER_SECOND * speed) + pauses_ms / 1000
