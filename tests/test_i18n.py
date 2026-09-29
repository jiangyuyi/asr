"""Unit tests for the localisation layer."""
import os
import sys

os.environ.setdefault("ASR_MM_HOME", os.path.join(os.path.dirname(__file__), ".testhome"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from asr_mm import i18n  # noqa: E402

LANGS = ["zh", "en", "ja"]


@pytest.fixture(autouse=True)
def reset_lang():
    i18n.set_language("zh")
    yield
    i18n.set_language("zh")


# ------------------------------------------------------------------ catalogue

def test_all_three_languages_exist():
    assert set(i18n.CATALOGS) == {"zh", "en", "ja"}


def test_catalogue_keys_identical_across_languages():
    zh_keys = set(i18n.ZH)
    for code in ("en", "ja"):
        assert set(i18n.CATALOGS[code]) == zh_keys, (
            f"{code} differs: missing={sorted(zh_keys - set(i18n.CATALOGS[code]))} "
            f"extra={sorted(set(i18n.CATALOGS[code]) - zh_keys)}")


def test_no_empty_translations():
    for code, cat in i18n.CATALOGS.items():
        for key, value in cat.items():
            assert value and value.strip(), f"{code}:{key} is empty"


def test_placeholders_match_across_languages():
    """Every {placeholder} in a template must exist in all three languages."""
    import re
    for key, template in i18n.ZH.items():
        want = set(re.findall(r"\{(\w+)", template))
        for code in ("en", "ja"):
            got = set(re.findall(r"\{(\w+)", i18n.CATALOGS[code][key]))
            assert want == got, f"{key} in {code}: {want} != {got}"


def test_templates_render_without_type_errors():
    for code in LANGS:
        i18n.set_language(code)
        for key, template in i18n.CATALOGS[code].items():
            names = _placeholders(template)
            args = {n: "X" for n in names}
            out = i18n.t(key, **args)
            assert "{" not in out, f"{code}:{key} left a placeholder: {out!r}"


def _placeholders(template: str) -> list[str]:
    import re
    return re.findall(r"\{(\w+)[^}]*\}", template)


# ------------------------------------------------------------------ behaviour

@pytest.mark.parametrize("code,expected", [
    ("zh", "zh"), ("en", "en"), ("ja", "ja"),
    ("zh-CN", "zh"), ("zh_CN", "zh"), ("ja-JP", "ja"), ("ja_JP.UTF-8", "ja"),
    ("en-US", "en"), ("en_GB", "en"), ("JA-jp", "ja"), ("English", "en"),
    ("japanese", "ja"), ("simplified chinese", "zh"),
])
def test_language_aliases(code, expected):
    assert i18n.resolve(code) == expected


def test_unknown_language_resolves_to_none():
    assert i18n.resolve("klingon") is None
    assert i18n.resolve("") is None
    assert i18n.resolve(None) is None


def test_set_language_falls_back_on_garbage():
    assert i18n.set_language("klingon") == i18n.DEFAULT_LANG
    assert i18n.set_language("ja") == "ja"
    assert i18n.get_language() == "ja"


def test_switching_changes_output():
    i18n.set_language("zh")
    zh = i18n.t("run")
    i18n.set_language("en")
    en = i18n.t("run")
    i18n.set_language("ja")
    ja = i18n.t("run")
    assert len({zh, en, ja}) == 3, "the three languages must differ"


def test_key_argument_does_not_collide():
    """t("cli.models.default", key="nano") — the param is positional-only."""
    i18n.set_language("en")
    assert "nano" in i18n.t("cli.models.default", key="nano")


def test_missing_key_falls_back_to_default_catalog():
    i18n.set_language("en")
    saved = i18n.CATALOGS["en"].pop("cli.dash")
    try:
        assert i18n.t("cli.dash") == i18n.ZH["cli.dash"]
    finally:
        i18n.CATALOGS["en"]["cli.dash"] = saved


def test_unknown_key_returns_the_key_itself():
    assert i18n.t("definitely.not.a.key") == "definitely.not.a.key"


def test_missing_kwarg_leaves_template_intact():
    i18n.set_language("en")
    out = i18n.t("err.not_a_file")
    assert "{path}" in out


def test_available_languages_use_native_names():
    names = [native for _code, native in i18n.available_languages()]
    assert names == ["简体中文", "English", "日本語"]


# ------------------------------------------------------------------- padding

def test_display_width_counts_cjk_as_two():
    assert i18n.display_width("abc") == 3
    assert i18n.display_width("中文") == 4
    assert i18n.display_width("abc中文") == 7


def test_pad_aligns_by_display_width():
    for text in ("abc", "中文", "abc中", "中文abc"):
        assert i18n.display_width(i18n.pad(text, 10)) == 10, text


def test_pad_right_align():
    assert i18n.pad("中文", 6, "right") == "  中文"
    assert i18n.display_width(i18n.pad("x", 6, "right")) == 6


def test_pad_does_not_truncate():
    assert i18n.pad("verylongvalue", 4) == "verylongvalue"


# ------------------------------------------------------------------ detection

def test_detect_returns_a_known_language():
    assert i18n.detect_system_language() in LANGS


def test_detect_honours_locale_env(monkeypatch):
    monkeypatch.setenv("LC_ALL", "ja_JP.UTF-8")
    assert i18n.detect_system_language() == "ja"
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    assert i18n.detect_system_language() == "en"


def test_set_language_none_detects(monkeypatch):
    monkeypatch.setenv("LC_ALL", "ja_JP.UTF-8")
    assert i18n.set_language(None) == "ja"
