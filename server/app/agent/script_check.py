"""口播稿检查：纯确定性代码。规则明确的事情交给代码，比让模型自己数字数准，而且免费。"""

from app.tts.chunker import CHARS_PER_SECOND, count_units

# 广告法常见极限用语（节选）。按需扩充，每加一个词都要考虑误伤（例如"最近"不该命中）。
BANNED_WORDS = [
    "最好",
    "最佳",
    "最强",
    "最低价",
    "最便宜",
    "最高级",
    "最先进",
    "最受欢迎",
    "第一",
    "No.1",
    "NO.1",
    "TOP1",
    "顶级",
    "极致",
    "国家级",
    "世界级",
    "全网最",
    "100%",
    "百分之百",
    "绝对",
    "永久",
    "万能",
    "根治",
    "无副作用",
    "零风险",
    "史无前例",
    "独一无二",
    "空前绝后",
    "首选",
    "唯一",
]

MAX_SEGMENT_UNITS = 40
TOLERANCE = 0.10


def check_script(segments: list[dict], target_seconds: int, speed: float = 1.0) -> dict:
    texts = [s["text"] for s in segments]
    full = "".join(texts)
    units = count_units(full)
    pauses = sum(int(s.get("pause_ms", 0)) for s in segments[:-1])
    est = units / (CHARS_PER_SECOND * speed) + pauses / 1000

    long_segments = [
        {"index": i, "units": count_units(t)} for i, t in enumerate(texts) if count_units(t) > MAX_SEGMENT_UNITS
    ]
    banned = sorted({w for w in BANNED_WORDS if w.lower() in full.lower()})
    deviation = (est - target_seconds) / target_seconds if target_seconds else 0

    problems = []
    if abs(deviation) > TOLERANCE:
        need = round(target_seconds * CHARS_PER_SECOND * speed - pauses / 1000 * CHARS_PER_SECOND * speed)
        problems.append(
            f"估算时长 {est:.1f} 秒，目标 {target_seconds} 秒，偏差 {deviation:+.0%}；"
            f"建议总字数调整到约 {need} 字（当前 {units} 字）"
        )
    if long_segments:
        problems.append(f"有 {len(long_segments)} 段超过 {MAX_SEGMENT_UNITS} 字，请拆短")
    if banned:
        problems.append(f"包含广告法违禁词：{'、'.join(banned)}")

    return {
        "ok": not problems,
        "units": units,
        "estimated_seconds": round(est, 1),
        "target_seconds": target_seconds,
        "segments": len(segments),
        "long_segments": long_segments,
        "banned_words": banned,
        "problems": problems,
    }
