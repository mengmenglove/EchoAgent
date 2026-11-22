import numpy as np

from app.tts.audio import concat, read_wav, to_wav_bytes, wav_info
from app.tts.subtitles import to_srt, to_vtt
from app.tts.verify import cer

RATE = 24000


def tone(seconds: float, rate: int = RATE) -> bytes:
    return to_wav_bytes(np.full(int(rate * seconds), 0.1, dtype="float32"), rate)


def test_concat_spans_include_pauses():
    wav, rate, spans = concat([(tone(1.0), 500), (tone(2.0), 0)])
    assert rate == RATE
    assert spans == [[0, 1000], [1500, 3500]]
    assert wav_info(wav) == (RATE, 3500)


def test_concat_resamples_mismatched_rate():
    wav, rate, spans = concat([(tone(1.0), 0), (tone(1.0, rate=16000), 0)])
    samples, sr = read_wav(wav)
    assert sr == RATE
    assert abs(len(samples) - 2 * RATE) <= 1
    assert spans[1] == [1000, 2000]


def test_srt_and_vtt_format():
    texts, spans = ["你好。", "再见。"], [[0, 1250], [3_725_400, 3_727_000]]
    assert to_srt(texts, spans) == (
        "1\n00:00:00,000 --> 00:00:01,250\n你好。\n\n2\n01:02:05,400 --> 01:02:07,000\n再见。\n"
    )
    assert to_vtt(texts, spans).startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.250\n你好。")


def test_cer_ignores_punctuation():
    assert cer("你好，世界。", "你好世界") == 0
    assert cer("今天天气很好", "今天天汽很好") == 1 / 6
    assert cer("", "随便") == 0
