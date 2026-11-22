"""管理命令。

uv run python -m app.cli seed-voices                # 写入系统音色（读取 voices.json）
uv run python -m app.cli add-voice --name 沉稳男声 --audio /path/ref.wav --text "录音原文" --tags 沉稳,男声
uv run python -m app.cli codes --credits 100 --count 10   # 生成兑换码
uv run python -m app.cli stats                      # 最近 7 天的任务与成本
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.config import SERVER_DIR, settings
from app.db import SessionLocal
from app.models import Job, JobStatus, LLMUsage, RedeemCode, Voice
from app.services.billing import new_code

VOICES_FILE = SERVER_DIR / "voices.json"


async def add_voice(name: str, audio: str, text: str, tags: list[str], description: str = "") -> None:
    path = Path(audio).expanduser().resolve()  # noqa: ASYNC240  命令行工具，不在服务进程里
    if not path.exists():
        raise SystemExit(f"找不到参考音频：{path}")
    async with SessionLocal() as db:
        existing = await db.scalar(select(Voice).where(Voice.owner_id.is_(None), Voice.name == name))
        v = existing or Voice(owner_id=None, name=name)
        v.ref_audio_path, v.ref_text, v.tags, v.description = str(path), text, tags, description
        db.add(v)
        await db.commit()
        print(("更新" if existing else "新增") + f"系统音色：{name}  id={v.id}")


async def seed_voices() -> None:
    if not VOICES_FILE.exists():
        # F5 自带的英文示例音色，至少能让链路跑起来。中文效果差，请尽快录中文参考音色。
        example = settings.f5_home / ".venv/lib/python3.12/site-packages/f5_tts/infer/examples/basic/basic_ref_en.wav"
        print(f"没有找到 {VOICES_FILE.name}，先写入 F5 自带的英文示例音色（中文效果较差）")
        await add_voice(
            "示例音色（英文参考）",
            str(example),
            "Some call me nature, others call me mother nature.",
            ["示例", "女声"],
            "F5 自带示例。合成中文会带口音，仅用于调试",
        )
        return
    for item in json.loads(VOICES_FILE.read_text(encoding="utf-8")):
        audio = item["audio"]
        if not Path(audio).is_absolute():
            audio = str(VOICES_FILE.parent / audio)
        await add_voice(item["name"], audio, item["text"], item.get("tags", []), item.get("description", ""))


async def make_codes(credits: int, count: int) -> None:
    async with SessionLocal() as db:
        codes = [RedeemCode(code=new_code(), credits=credits) for _ in range(count)]
        db.add_all(codes)
        await db.commit()
    for c in codes:
        print(f"{c.code}\t{credits}")


async def stats(days: int) -> None:
    since = datetime.now(UTC) - timedelta(days=days)
    async with SessionLocal() as db:
        rows = (
            await db.execute(select(Job.status, func.count()).where(Job.created_at >= since).group_by(Job.status))
        ).all()
        usage = (
            await db.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(LLMUsage.cost_usd), 0),
                    func.coalesce(func.sum(LLMUsage.input_tokens), 0),
                    func.coalesce(func.sum(LLMUsage.cache_read_tokens), 0),
                    func.coalesce(func.sum(LLMUsage.output_tokens), 0),
                ).where(LLMUsage.created_at >= since)
            )
        ).one()
        brief_jobs = await db.scalar(
            select(func.count(func.distinct(LLMUsage.job_id))).where(LLMUsage.created_at >= since)
        )
        succeeded = await db.scalar(
            select(func.count()).where(Job.created_at >= since, Job.status == JobStatus.succeeded)
        )
    total = sum(n for _, n in rows)
    print(f"最近 {days} 天：任务 {total} 个，成功 {succeeded or 0} 个")
    for status, n in rows:
        print(f"  {status:<13}{n}")
    calls, cost, inp, cache_read, out = usage
    print(f"模型调用 {calls} 次，花费 ${float(cost):.4f}")
    if brief_jobs:
        print(f"  每个需求模式任务平均 ${float(cost) / brief_jobs:.4f}，平均 {calls / brief_jobs:.1f} 轮")
    if inp + cache_read:
        print(f"  缓存命中率 {cache_read / (inp + cache_read):.0%}（cache_read / 全部输入）")
    print(f"  输出 Token {out}（包含思考过程）")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed-voices")
    av = sub.add_parser("add-voice")
    av.add_argument("--name", required=True)
    av.add_argument("--audio", required=True)
    av.add_argument("--text", required=True, help="参考音频里念的原文，必须逐字一致")
    av.add_argument("--tags", default="")
    av.add_argument("--description", default="")
    c = sub.add_parser("codes")
    c.add_argument("--credits", type=int, required=True)
    c.add_argument("--count", type=int, default=1)
    st = sub.add_parser("stats")
    st.add_argument("--days", type=int, default=7)
    args = p.parse_args()

    match args.cmd:
        case "seed-voices":
            asyncio.run(seed_voices())
        case "add-voice":
            tags = [t.strip() for t in args.tags.split(",") if t.strip()]
            asyncio.run(add_voice(args.name, args.audio, args.text, tags, args.description))
        case "codes":
            asyncio.run(make_codes(args.credits, args.count))
        case "stats":
            asyncio.run(stats(args.days))


if __name__ == "__main__":
    main()
