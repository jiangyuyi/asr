"""Extra files shipped inside the macOS archives.

A zip downloaded from GitHub lands with the ``com.apple.quarantine`` attribute
set. macOS then refuses to ``dlopen`` any unsigned dylib inside it, which is
what a PyInstaller bundle is full of. The user sees:

    Failed to load Python shared library .../\\_internal/Python
    ... not valid for use in process: library load disallowed by system policy

We cannot sign and notarise without an Apple Developer account, so the archive
carries a double-clickable launcher that clears the attribute first. That turns
a terminal ritual into one click, and leaves the bundle genuinely cleared so
every later launch just works.

Each archive gets a launcher pointing at the binary that archive actually
contains — the console and GUI bundles ship separately, so a fixed path would
point at a file that is not there.
"""
from __future__ import annotations

# bundle directory -> binary inside it
BUNDLES = {
    "asr-mm": "asr-mm",
    "asr-mm-gui": "asr-mm-gui",
}

_LAUNCHER = """#!/bin/bash
# asr-mm — clears the macOS quarantine mark, then starts {target}.
#
# Archives downloaded from GitHub are marked quarantined, and macOS refuses to
# load unsigned libraries from a quarantined bundle. Removing the mark once makes
# every subsequent launch work normally.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ -n "$(xattr -p com.apple.quarantine "$DIR" 2>/dev/null || true)" ]]; then
  echo "Clearing the macOS quarantine mark (first run only)…"
  xattr -cr "$DIR" 2>/dev/null || true
fi

exec "$DIR/{path}" "$@"
"""


def _readme(target_name: str, launcher: str) -> str:
    return f"""asr-mm — 视频指定时间段 → 中文语音转写
asr-mm — video segment transcription
asr-mm — 動画区間の文字起こし

────────────────────────────────────────────────────────────
首次运行（只做一次）
────────────────────────────────────────────────────────────

双击上方的「{launcher}」启动。

它会自动清除 macOS 的隔离标记（quarantine）。从 GitHub 下载的压缩包会被标记，
而未签名的程序在标记状态下 macOS 不允许加载内部库。清除之后，之后直接双击
{target_name} 即可。

也可以在终端手动执行：

    xattr -cr ~/Downloads/{target_name}
    ./{target_name}

────────────────────────────────────────────────────────────
First run (once)
────────────────────────────────────────────────────────────

Double-click "{launcher}" above. It clears the macOS quarantine mark
automatically: archives downloaded from GitHub are marked quarantined, and
macOS will not load unsigned libraries from them. After that, double-clicking
{target_name} works directly.

────────────────────────────────────────────────────────────
システム固有の初回起動（一度だけ）
────────────────────────────────────────────────────────────

上記の「{launcher}」をダブルクリックしてください。GitHub からダウンロード
した ZIP には隔離マークが付くため、macOS が未署名のライブラリを読み込めません。
起動スクリプトが自動で解除します。2 回目以降は {target_name} を直接
ダブルクリックで起動できます。

────────────────────────────────────────────────────────────
模型 / Models
────────────────────────────────────────────────────────────

首次使用请在界面点「工具 → 下载缺失模型」，或运行命令行版本：

    ./asr-mm/asr-mm setup

  Nano        911 MB  标点完整、中文准确率最高（默认）
  Paraformer  228 MB  最快，输出不带标点
  SenseVoice  244 MB  唯一支持显卡加速

模型只下载一次，之后可完全离线使用。视频文件不会被上传。
"""


def files_for(bundle: str) -> dict[str, str]:
    """``{archive-member name: contents}`` for one macOS archive."""
    target = BUNDLES.get(bundle, bundle)
    stem = "Run asr-mm" if bundle == "asr-mm" else "Open asr-mm"
    launcher = f"{stem}.command"
    return {
        launcher: _LAUNCHER.format(path=f"{bundle}/{target}", target=target),
        "README-macOS.txt": _readme(target_name=target, launcher=launcher),
    }
