import pytest

from app.tts.text_norm import normalize


@pytest.mark.parametrize(
    "src, expected",
    [
        ("价格是299元", "价格是二百九十九元。"),
        ("只要¥99", "只要九十九元。"),
        ("续航提升35%", "续航提升百分之三十五。"),
        ("2025年新款", "二零二五年新款。"),
        ("3-5天到货", "三到五天到货。"),
        ("早上9:30开播", "早上九点三十开播。"),
        ("晚上8:00见", "晚上八点见。"),
        ("客服电话10086", "客服电话一零零八六。"),
        ("重量1.5kg", "重量一点五公斤。"),
        ("【限时】抢购！", "限时抢购！"),
        ("你好 世界", "你好世界。"),
    ],
)
def test_normalize(src, expected):
    assert normalize(src) == expected


def test_lexicon_overrides_and_is_case_insensitive():
    assert normalize("新款IPHONE来了", {"iPhone": "爱疯"}) == "新款爱疯来了。"


def test_lexicon_longest_first():
    lex = {"App": "A P P", "AppStore": "苹果商店"}
    assert normalize("去AppStore下载App", lex) == "去苹果商店下载A P P。"


def test_english_kept_as_is():
    assert normalize("I have 3 cats and it costs $25.") == "I have 3 cats and it costs $25."
    assert normalize("Hello! **Great** question") == "Hello! Great question."
    assert normalize('" but that\'s okay, you said "I go,"') == "but that's okay, you said I go."
