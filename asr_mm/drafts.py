"""转写草稿的持久化——防止编辑过的内容被覆盖或因意外退出而丢失。

**为什么需要它。** 转写结果和用户的编辑原本只活在内存里（``self.result``
和表格单元格）。这带来两个必然的丢失场景：

1. 转写完成后又手改了内容，此时再点一次「开始转写」，新结果会**整个替换**
   表格，手改的部分没有任何地方留下。
2. 编辑过程中进程意外退出（崩溃 / 断电 / 任务管理器结束进程），内存里的
   内容全部消失，且没有任何可恢复的痕迹。

两种都实际发生过。于是把状态落盘。

**存在哪。** ``home_root()/drafts/``，也就是应用自己的数据目录
（Windows: ``%LOCALAPPDATA%\\asr-mm``，macOS: ``~/Library/Application
Support/asr-mm``）。不放应用安装目录：macOS 上 ``/Applications`` 是只读的，
而且把用户数据写进安装目录在升级时会被覆盖掉。

**写盘策略。** 写临时文件再 ``os.replace`` 原子替换——直接覆盖的话，
写到一半崩溃会留下一个半截 JSON，下次载入就废了。

**这不是备份系统。** 草稿只保留最近的若干份（见 :func:`prune`），用来在
误操作后把东西找回来，不是长期归档。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

# 保留策略：份数上限 + 最长保存天数。两个都留着，光看份数不知道什么时候
# 清理的，光看时间又会让磁盘上堆一堆。
KEEP_LIMIT = 20
MAX_AGE_DAYS = 30

DRAFT_SUFFIX = ".draft.json"


@dataclass
class Draft:
    """一次转写的结果 + 用户当时的编辑。

    ``segments`` 存的是**表格里的当前文本**（可能已被手改），不是引擎的
    原始输出——恢复草稿时要的就是手改后的版本。
    """

    id: str
    created_at: float
    updated_at: float
    source: str
    source_duration: float = 0.0
    range_start: float = 0.0
    range_end: float = 0.0
    applied_start: float = 0.0
    applied_end: float = 0.0
    model: str = ""
    model_label: str = ""
    elapsed: float = 0.0
    audio_seconds: float = 0.0
    segments: list[dict] = field(default_factory=list)
    translations: dict[str, list[str]] = field(default_factory=dict)
    # 引擎产出的原样，键是 "行,列"。存它是为了载入草稿之后撤销按钮还能用——
    # 没有基线的话，手改过的行和没改过的行就分不出来了。
    initial_cells: dict[str, str] = field(default_factory=dict)
    edited: bool = False

    # ---------------------------------------------------------------- 转换
    @classmethod
    def build(cls, draft_id: str, result, segments=None,
              translations: dict[str, list[str]] | None = None,
              initial_cells: dict | None = None,
              created_at: float | None = None) -> "Draft":
        """From a :class:`~asr_mm.transcribe.Transcript` plus the table's text.

        ``segments`` 是表格当前各行的 ``(start, end, text, suspicious)``；
        不给就用转写结果本身。
        """
        now = time.time()
        rows = segments if segments is not None else [
            {"start": s.start, "end": s.end, "text": s.text,
             "suspicious": bool(getattr(s, "suspicious", False))}
            for s in result.segments
        ]
        return cls(
            id=draft_id,
            created_at=now if created_at is None else float(created_at),
            updated_at=now,
            source=str(getattr(result, "source", "") or ""),
            source_duration=float(getattr(result, "source_duration", 0.0) or 0.0),
            range_start=float(getattr(result, "range_start", 0.0) or 0.0),
            range_end=float(getattr(result, "range_end", 0.0) or 0.0),
            applied_start=float(getattr(result, "applied_start", 0.0) or 0.0),
            applied_end=float(getattr(result, "applied_end", 0.0) or 0.0),
            model=str(getattr(result, "model", "") or ""),
            model_label=str(getattr(result, "model_label", "") or ""),
            elapsed=float(getattr(result, "elapsed", 0.0) or 0.0),
            audio_seconds=float(getattr(result, "audio_seconds", 0.0) or 0.0),
            segments=list(rows),
            translations={k: list(v) for k, v in (translations or {}).items()},
            initial_cells={str(k): str(v)
                           for k, v in (initial_cells or {}).items()},
        )

    def to_transcript(self):
        """Back into a Transcript so the GUI can show it again."""
        from .transcribe import Segment, Transcript

        segs = [Segment(start=float(r.get("start", 0.0)),
                        end=float(r.get("end", 0.0)),
                        text=str(r.get("text", "")),
                        suspicious=bool(r.get("suspicious", False)))
                for r in self.segments]
        return Transcript(
            source=self.source,
            source_duration=self.source_duration,
            range_start=self.range_start,
            range_end=self.range_end,
            applied_start=self.applied_start,
            applied_end=self.applied_end,
            model=self.model,
            model_label=self.model_label,
            segments=segs,
            elapsed=self.elapsed,
            audio_seconds=self.audio_seconds,
        )

    # ---------------------------------------------------------------- 序列化
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "source_duration": self.source_duration,
            "range_start": self.range_start,
            "range_end": self.range_end,
            "applied_start": self.applied_start,
            "applied_end": self.applied_end,
            "model": self.model,
            "model_label": self.model_label,
            "elapsed": self.elapsed,
            "audio_seconds": self.audio_seconds,
            "segments": self.segments,
            "translations": self.translations,
            "initial_cells": self.initial_cells,
            "edited": self.edited,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Draft":
        return cls(
            id=str(data.get("id", "")),
            created_at=float(data.get("created_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
            source=str(data.get("source", "")),
            source_duration=float(data.get("source_duration", 0.0)),
            range_start=float(data.get("range_start", 0.0)),
            range_end=float(data.get("range_end", 0.0)),
            applied_start=float(data.get("applied_start", 0.0)),
            applied_end=float(data.get("applied_end", 0.0)),
            model=str(data.get("model", "")),
            model_label=str(data.get("model_label", "")),
            elapsed=float(data.get("elapsed", 0.0)),
            audio_seconds=float(data.get("audio_seconds", 0.0)),
            segments=list(data.get("segments") or []),
            translations=dict(data.get("translations") or {}),
            initial_cells=dict(data.get("initial_cells") or {}),
            edited=bool(data.get("edited", False)),
        )


# ------------------------------------------------------------------ 存取
def drafts_dir() -> Path:
    d = paths.home_root() / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_id() -> str:
    """A sortable, collision-free id: time prefix + random suffix."""
    import uuid
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def path_for(draft_id: str) -> Path:
    # The id ends up in a filename; keep it to safe characters so a weird
    # source path can't produce a path we cannot open.
    safe = "".join(c for c in draft_id if c.isalnum() or c in "-_")[:64] or "draft"
    return drafts_dir() / f"{safe}{DRAFT_SUFFIX}"


def save(draft: Draft) -> Path:
    """Write the draft atomically. Returns the path it landed on.

    写临时文件再 rename：直接覆盖的话，写到一半崩掉会留下半截 JSON，
    下次载入就废了。rename 在同一分区上是原子的，所以磁盘上永远要么是
    完整的旧文件，要么是完整的新文件。
    """
    target = path_for(draft.id)
    tmp = target.with_suffix(target.suffix + ".tmp")
    payload = json.dumps(draft.to_dict(), ensure_ascii=False, indent=1)
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        # 写失败就把临时文件收掉，别在目录里堆垃圾。
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return target


def load(path: Path) -> Draft | None:
    """Read a draft. A damaged file returns None instead of raising.

    草稿是被自动写出来的，损坏是可能的（比如断电时写到一半）。读不出来就当
    它不存在，不能因为一个坏文件把整个列表功能搞崩。
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return Draft.from_dict(data)
    except (TypeError, ValueError):
        return None


def list_drafts() -> list[Draft]:
    """Every readable draft, newest first."""
    out: list[Draft] = []
    try:
        files = list(drafts_dir().glob(f"*{DRAFT_SUFFIX}"))
    except OSError:
        return out
    for f in files:
        d = load(f)
        if d is not None:
            out.append(d)
    out.sort(key=lambda d: d.updated_at, reverse=True)
    return out


def delete(draft_id: str) -> bool:
    p = path_for(draft_id)
    try:
        p.unlink()
        return True
    except OSError:
        return False


def prune(keep: int = KEEP_LIMIT, max_age_days: int = MAX_AGE_DAYS) -> int:
    """Drop old drafts. Returns how many were removed.

    两把尺子一起用：超龄的一律删，超量的按时间从旧到新删。留 ``keep`` 份
    保底，避免刚转写完的东西被自己清掉。
    """
    items = list_drafts()
    removed = 0
    now = time.time()
    fresh: list[Draft] = []
    for d in items:
        if max_age_days and now - d.updated_at > max_age_days * 86400:
            if delete(d.id):
                removed += 1
        else:
            fresh.append(d)
    if keep and len(fresh) > keep:
        for d in fresh[keep:]:          # fresh 是新到旧
            if delete(d.id):
                removed += 1
    removed += _clear_stale_tmp()
    return removed


def _clear_stale_tmp() -> int:
    """Delete leftover ``*.tmp`` files from a write that never finished."""
    n = 0
    try:
        files = list(drafts_dir().glob(f"*{DRAFT_SUFFIX}.tmp"))
    except OSError:
        return 0
    for f in files:
        try:
            f.unlink()
            n += 1
        except OSError:
            pass
    return n
