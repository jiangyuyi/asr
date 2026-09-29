"""Unit tests for the pure logic — no subprocesses, no models, no network."""
import os
import sys

os.environ.setdefault("ASR_MM_HOME", os.path.join(os.path.dirname(__file__), ".testhome"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from asr_mm import catalog, srt, transcribe  # noqa: E402


# ------------------------------------------------------------------ timecodes

@pytest.mark.parametrize("raw,expected", [
    ("00:03:20", 200.0),
    ("03:20", 200.0),
    ("200", 200.0),
    ("200.5", 200.5),
    ("1:00:00", 3600.0),
    ("00:00:07.250", 7.25),
    (None, None),
    ("", None),
])
def test_parse_timecode(raw, expected):
    assert transcribe.parse_timecode(raw) == expected


def test_parse_timecode_numeric():
    assert transcribe.parse_timecode(200) == 200.0
    assert transcribe.parse_timecode(0) == 0.0


def test_parse_timecode_rejects_garbage():
    with pytest.raises(ValueError):
        transcribe.parse_timecode("三分钟二十秒")


# ------------------------------------------------------------------ srt io

SRT = """1
00:00:00,300 --> 00:00:10,400
第一段文字

2
00:00:12,350 --> 00:00:29,980
第二段文字，
跨两行
"""


def test_parse_srt_basic():
    cues = srt.parse_srt(SRT)
    assert len(cues) == 2
    assert cues[0].start == pytest.approx(0.3)
    assert cues[0].end == pytest.approx(10.4)
    assert cues[0].text == "第一段文字"
    assert cues[1].duration == pytest.approx(17.63)


def test_parse_srt_joins_multiline_text():
    assert srt.parse_srt(SRT)[1].text == "第二段文字， 跨两行"


def test_parse_srt_skips_junk_without_raising():
    junk = "not a cue\n\n-->\n\n1\n00:00:01,000 --> 00:00:02,000\nok\n"
    cues = srt.parse_srt(junk)
    assert [c.text for c in cues] == ["ok"]


def test_parse_srt_drops_empty_cues():
    only_ts = "1\n00:00:01,000 --> 00:00:02,000\n\n"
    assert srt.parse_srt(only_ts) == []


def test_srt_roundtrip():
    cues = srt.parse_srt(SRT)
    assert srt.parse_srt(srt.render_srt(cues)) == cues


def test_format_ts():
    assert srt.format_ts(0.3) == "00:00:00,300"
    assert srt.format_ts(3661.5, comma=False) == "01:01:01.500"
    assert srt.format_ts(-5) == "00:00:00,000"


def test_render_txt_adds_terminator_only_when_missing():
    out = srt.render_txt(srt.parse_srt(
        "1\n00:00:00,000 --> 00:00:01,000\n好的\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\n是吗？\n"))
    assert out == "好的。是吗？"


# ------------------------------------------------------- suspicious detection

def test_visible_chars_strips_punctuation():
    assert transcribe.visible_chars("，。！？ 好的") == 2
    assert transcribe.visible_chars("...") == 0


def test_short_noise_cue_is_flagged():
    seg = transcribe._flag(srt.Cue(65.44, 66.16, "战争"), 0.0)
    assert seg.suspicious is True


def test_normal_cue_is_not_flagged():
    assert transcribe._flag(srt.Cue(0.0, 10.0, "大家互相交流啊。"), 0.0).suspicious is False
    assert transcribe._flag(srt.Cue(0.0, 0.5, "他也没"), 0.0).suspicious is False


# ------------------------------------------------------------------- catalog

def test_every_model_resolves_by_key_and_alias():
    assert catalog.resolve_model("nano").key == "nano"
    assert catalog.resolve_model("Qwen3").key == "nano"
    assert catalog.resolve_model("fast").key == "paraformer"
    assert catalog.resolve_model("SENSEVOICE").key == "sensevoice"


def test_unknown_model_raises():
    with pytest.raises(KeyError):
        catalog.resolve_model("whisper")


def test_default_model_is_available():
    assert catalog.DEFAULT_MODEL in catalog.MODELS


def test_every_model_bundles_vad():
    for spec in catalog.MODELS.values():
        assert "fsmn-vad.gguf" in [f.filename for f in spec.files], spec.key


def test_encoder_model_is_listed_as_a_file():
    # Nano passes --enc <file>; if that file is not downloaded the engine breaks.
    nano = catalog.resolve_model("nano")
    assert nano.encoder_file in [f.filename for f in nano.files]


def test_model_sizes_are_plausible():
    for spec in catalog.MODELS.values():
        total = sum(f.size for f in spec.files)
        assert 1_000_000 < total < 2_000_000_000, spec.key


def test_runtimes_have_valid_checksums():
    for spec in catalog.RUNTIMES.values():
        assert len(spec.sha256) == 64, spec.key
        assert spec.sha256 == spec.sha256.lower(), spec.key
        assert spec.url.endswith(spec.archive), spec.key
