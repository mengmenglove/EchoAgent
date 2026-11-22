"""文本规整：把"写给人看"的文字，变成"给 TTS 念"的文字。

TTS 最常见的问题是数字、符号、英文读错。规整后的文本只用于合成，
字幕依然显示原文。每条规则在 tests/test_text_norm.py 里都有用例。
"""

import re

import cn2an

_DIGITS = "零一二三四五六七八九"

# 全角/特殊符号 → 常规写法
_PUNCT_MAP = str.maketrans(
    {
        "，": "，",
        ",": "，",
        "!": "！",
        "?": "？",
        ";": "；",
        ":": "：",
        "（": "，",
        "）": "，",
        "(": "，",
        ")": "，",
        "【": "",
        "】": "",
        "「": "",
        "」": "",
        "“": "",
        "”": "",
        '"': "",
        "*": "",
        "#": "",
    }
)

_SYMBOLS = [
    ("&", "和"),
    ("+", "加"),
    ("=", "等于"),
    ("@", "艾特"),
    ("℃", "摄氏度"),
    ("°C", "摄氏度"),
    ("kg", "公斤"),
    ("km", "公里"),
    ("¥", ""),  # "¥99" → "99元" 由下面的价格规则处理
    ("￥", ""),
]


def digits_one_by_one(s: str) -> str:
    """逐位读：2025 → 二零二五（年份、电话、编号都这样读）。"""
    return "".join(_DIGITS[int(c)] if c.isdigit() else c for c in s)


def _number(m: re.Match) -> str:
    return cn2an.an2cn(m.group(0), "low")


def apply_lexicon(text: str, lexicon: dict[str, str] | None) -> str:
    """用户自定义读音，长词优先，英文不区分大小写。"""
    if not lexicon:
        return text
    for word in sorted(lexicon, key=len, reverse=True):
        text = re.sub(re.escape(word), lexicon[word], text, flags=re.IGNORECASE)
    return text


def normalize(text: str, lexicon: dict[str, str] | None = None) -> str:
    text = apply_lexicon(text, lexicon)
    text = text.translate(_PUNCT_MAP)

    # 价格：¥99 / ￥99.9 → 99元（符号在前的读成"元"）
    text = re.sub(r"[¥￥]\s*(\d+(?:\.\d+)?)", r"\1元", text)
    for sym, word in _SYMBOLS:
        text = text.replace(sym, word)

    # 百分比：35% → 百分之三十五（必须在通用数字规则之前）
    text = re.sub(r"(\d+(?:\.\d+)?)\s*[%％]", lambda m: "百分之" + cn2an.an2cn(m.group(1), "low"), text)
    # 范围：3-5天、3~5 天 → 三到五天
    text = re.sub(r"(\d+(?:\.\d+)?)\s*[-~～—]\s*(\d+(?:\.\d+)?)", r"\1到\2", text)
    # 年份：2025年 → 二零二五年
    text = re.sub(r"(\d{4})(?=年)", lambda m: digits_one_by_one(m.group(1)), text)
    # 时间：9:30 → 九点三十
    text = re.sub(
        r"(\d{1,2})[:：](\d{2})",
        lambda m: (
            cn2an.an2cn(m.group(1), "low") + "点" + cn2an.an2cn(str(int(m.group(2))), "low")
            if m.group(2) != "00"
            else cn2an.an2cn(m.group(1), "low") + "点"
        ),
        text,
    )
    # 5 位及以上的纯数字（电话、编号、型号）逐位读
    text = re.sub(r"\d{5,}", lambda m: digits_one_by_one(m.group(0)), text)
    # 其余数字按数值读：299 → 二百九十九，3.5 → 三点五
    text = re.sub(r"\d+(?:\.\d+)?", _number, text)

    text = re.sub(r"[ \t　]+", " ", text).strip()
    text = re.sub(r"(?<=[一-鿿]) (?=[一-鿿])", "", text)  # 中文之间的空格去掉
    text = re.sub(r"[，、]{2,}", "，", text)
    text = text.strip("，、 ")
    if text and text[-1] not in "。！？":
        text += "。"
    return text
