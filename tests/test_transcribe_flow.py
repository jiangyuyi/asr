"""转写主流程的崩溃回归。

1.5.1 用户实际遇到的崩溃：

    NameError: cannot access free variable 'format_ts' where it is not
    associated with a value in enclosing scope
      File "asr_mm\\gui\\worker.py", line 42, in run
      File "asr_mm\\transcribe.py", line 193, in transcribe
      File "asr_mm\\transcribe.py", line 193, in <genexpr>

原因：transcribe() 里有一行多余的 `from .srt import format_ts`，只写在
「区间太短」的错误分支里。它让 format_ts 变成 transcribe() 的**局部变量**
（遮蔽了模块级 import），而该局部只在走进错误分支时才赋值。正常跑完时它
是空的，于是 193 行那个只在「有疑似噪音片段且没勾过滤」时才执行的 genexpr
一执行就抛 NameError。

所以本地测试没复现：用例都是干净片段，而且从没走过错误分支——
直到用户用整段视频（里面有没有说话的气口）才踩到。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from asr_mm import transcribe
from asr_mm.srt import Cue

SRC = Path(transcribe.__file__)


# ------------------------------------------------------------------ 结构防线

def test_format_ts_is_not_a_local_of_transcribe():
    """format_ts 必须解析到模块级，不能是 transcribe() 的局部变量。"""
    tree = ast.parse(SRC.read_text(encoding="utf-8-sig"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "transcribe")
    local_imports = set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                local_imports.add(a.asname or a.name.split(".")[0])
    assert "format_ts" not in local_imports, (
        "transcribe() 里又出现了一次 from ... import format_ts，"
        "它会遮蔽模块级 import 并在未赋值的分支上抛 NameError")


def test_the_name_resolves_globally():
    """跑一遍那个被遮蔽的名字，确认它确实走模块全局。"""
    tree = ast.parse(SRC.read_text(encoding="utf-8-sig"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "transcribe")
    args = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
    stores = {t.id for n in ast.walk(fn) for t in ast.walk(n)
              if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)}
    assert "format_ts" not in args, "format_ts 不该是参数"
    assert "format_ts" not in stores, "format_ts 不该在函数体内被赋值"
    # 真的调一次，确认解析到的是模块级那个（默认用逗号做毫秒分隔）
    assert transcribe.format_ts(1.5) == "00:00:01,500"


# ------------------------------------------------------------------ 行为防线

class _Info:
    duration = 66.13
    path = "fake.avi"
    size_mb = 50.0
    audio_codec = "pcm_s16le"
    sample_rate = 22050
    channels = 1
    has_audio = True
    has_video = True


class _Res:
    def __init__(self, cues):
        self.cues = cues
        self.warning = ""
        self.seconds = 2.0


def _make_engine(cues):
    """engine 是模块级函数 transcribe_wav(wav, model, ...)，不是实例方法。"""
    def transcribe_wav(_wav, _model, **kw):
        return _Res(cues)

    return type("FakeEngine", (), {
        "DEFAULT_MAXSEG_MS": 10000,
        "transcribe_wav": staticmethod(transcribe_wav),
    })


@pytest.fixture()
def video(tmp_path):
    p = tmp_path / "v.avi"
    p.write_bytes(b"x")
    return p


def _stub(tmp_path, monkeypatch, cues):
    def _probe(_src):
        return _Info()

    def _extract(_src, dst, start, end, loudnorm=False):
        Path(dst).write_bytes(b"RIFF")
        return Path(dst)

    monkeypatch.setattr(transcribe.media, "probe", _probe)
    monkeypatch.setattr(transcribe.media, "extract_audio", _extract)
    monkeypatch.setattr(transcribe, "engine", _make_engine(cues))


def test_flagged_segments_build_the_warning(tmp_path, monkeypatch, video):
    """用户崩溃的那条路径：有疑似噪音片段 + 没勾过滤 → 必须能生成提示。"""
    # 0.4s 的「嗯」会被 _flag 判为 suspicious
    _stub(tmp_path, monkeypatch,
          [Cue(1.0, 5.0, "一段正常的话。"),
           Cue(5.0, 5.4, "嗯"),
           Cue(5.5, 6.0, "又")])
    tr = transcribe.transcribe(video, drop_short=False)
    assert tr.segments, "应该保留片段"
    assert tr.warning, "有疑似噪音片段时必须给出提示"
    assert "00:00:05" in tr.warning, f"提示里应带时间码: {tr.warning!r}"


def test_no_flagged_no_crash(tmp_path, monkeypatch, video):
    """没有疑似片段时不能碰 193 行那个 genexpr（以前是靠运气躲过去的）。"""
    _stub(tmp_path, monkeypatch,
          [Cue(1.0, 5.0, "一段正常的话。"), Cue(5.0, 9.0, "另一段话。")])
    tr = transcribe.transcribe(video, drop_short=False)
    assert tr.warning == ""
    assert len(tr.segments) == 2


def test_drop_short_skips_the_preview(tmp_path, monkeypatch, video):
    """勾了过滤时只剩 dropped，提示不再拼接 preview。"""
    _stub(tmp_path, monkeypatch,
          [Cue(1.0, 5.0, "一段正常的话。"), Cue(5.0, 5.4, "嗯")])
    tr = transcribe.transcribe(video, drop_short=True)
    assert tr.warning == ""
    assert tr.dropped


def test_range_errors_still_readable(tmp_path, monkeypatch, video):
    """那两个用 format_ts 拼的错误信息必须还能用（这次没删功能）。"""
    _stub(tmp_path, monkeypatch, [])
    with pytest.raises(ValueError):        # 区间只有 0.01 秒
        transcribe.transcribe(video, start=10, end=10.01)
    with pytest.raises(ValueError):        # 超出 66.13 秒的视频长度
        transcribe.transcribe(video, start=999, end=1000)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
