"""字幕：用每段的起止时间 + 原文（不是规整后的文本）生成 SRT / VTT。"""


def _ts(ms: int, sep: str) -> str:
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(texts: list[str], spans: list[list[int]]) -> str:
    lines = []
    for i, (text, (start, end)) in enumerate(zip(texts, spans, strict=True), 1):
        lines += [str(i), f"{_ts(start, ',')} --> {_ts(end, ',')}", text, ""]
    return "\n".join(lines)


def to_vtt(texts: list[str], spans: list[list[int]]) -> str:
    lines = ["WEBVTT", ""]
    for text, (start, end) in zip(texts, spans, strict=True):
        lines += [f"{_ts(start, '.')} --> {_ts(end, '.')}", text, ""]
    return "\n".join(lines)
