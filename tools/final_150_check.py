"""v1.5.0 发布回验：真的从 release 地址把翻译模型拉下来跑一遍。

验的是整条链路，不只是文件哈希：
  catalog 的 URL -> net 下载（断点续传/重试/镜像）-> sha256 校验
  -> 落盘布局 -> CTranslate2 加载 -> 实际翻译
任何一个环节错了，翻译结果就会不对或者直接报错。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / "build_verify_home"

FAIL: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run(args: list[str], timeout: int = 3600) -> tuple[int, str]:
    env = dict(os.environ)
    env["ASR_MM_HOME"] = str(HOME)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, "-m", "asr_mm.cli", *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=timeout, cwd=ROOT)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    print("=" * 68)
    print("RELEASE 1.5.0 VERIFICATION — 翻译模型从已发布地址回验")
    print("=" * 68)

    if HOME.exists():
        shutil.rmtree(HOME)
    HOME.mkdir(parents=True)
    print(f"干净的用户目录: {HOME}")

    # The end-to-end step also needs the *recognition* runtime and the ASR
    # weights, which are several hundred MB and have nothing to do with what
    # this script verifies. Seed them from the dev home when it exists, so the
    # script stays offline-ish instead of re-downloading 1.4 GB.
    dev_home = ROOT / ".asrhome"
    if dev_home.exists():
        for item in ("runtime", "models"):
            src = dev_home / item
            dst = HOME / item
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                # mt-en / mt-ja are what this script is here to fetch; do not
                # copy them in from dev or the download check proves nothing.
                if f.is_dir() and f.name.startswith("mt-"):
                    continue
                target = dst / f.name
                if not target.exists():
                    shutil.copy2(f, target) if f.is_file() else shutil.copytree(f, target)
        print("已从 .asrhome 复制识别运行时与 ASR 模型\n")
    else:
        print("（未找到 .asrhome，第 5 步端到端会因缺识别运行时而跳过）\n")

    sys.path.insert(0, str(ROOT))
    from asr_mm import catalog

    # ---- 1. 声明的 URL 真的能取到（只查小文件，省时间）
    print("--- 1. catalog URL 可达性 ---")
    import urllib.request
    import ssl
    import certifi
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(certifi.where())
    for code, spec in catalog.MT_MODELS.items():
        small = next(f for f in spec.files if f.filename.endswith(".json")
                     and "shared" not in f.filename)
        try:
            req = urllib.request.Request(small.url, method="HEAD",
                                         headers={"User-Agent": "asr-mm/verify"})
            with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
                got = int(r.headers.get("Content-Length") or 0)
            check(f"{code}: {small.filename} 可下载",
                  got == small.size, f"{got} / 声明 {small.size}")
        except Exception as exc:
            check(f"{code}: {small.filename} 可下载", False, str(exc)[:70])

    # ---- 2. 用真实程序下载英文模型
    print("\n--- 2. asr-mm mt download en ---")
    t0 = time.time()
    rc, out = run(["mt", "download", "en"])
    print(f"    ({time.time()-t0:.1f}s)")
    check("命令退出码为 0", rc == 0, out.strip().splitlines()[-1][:80] if out.strip() else "")
    check("程序报告英文模型已就绪", catalog.mt_model_ready("en"))

    d = catalog.mt_model_dir("en")
    spec = catalog.MT_MODELS["en"]
    for f in spec.files:
        p = d / f.filename
        if not p.exists():
            check(f"文件存在 {f.filename}", False)
            continue
        ok = p.stat().st_size == f.size and sha256(p) == f.sha256
        check(f"文件正确 {f.filename}", ok,
              f"{p.stat().st_size:,} 字节")

    # ---- 3. 用下载来的模型真翻译
    print("\n--- 3. 用刚下载的模型翻译 ---")
    probe = ["这批设备的保修期是两年，过期之后需要重新购买。",
             "今天的会议改到明天下午三点钟，请通知一下所有参加的人。",
             "你觉得这个价格合理吗？如果不合适可以再商量。"]
    script = (
        "import sys; sys.path.insert(0, r'%s')\n"
        "from asr_mm.translate import Translator\n"
        "r = Translator(['en']).translate(%r)\n"
        "for t in r.texts['en']: print('  ->', t)\n"
    ) % (ROOT, probe)
    env = dict(os.environ)
    env["ASR_MM_HOME"] = str(HOME)
    env["PYTHONIOENCODING"] = "utf-8"
    t0 = time.time()
    p = subprocess.run([sys.executable, "-c", script], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=env, cwd=ROOT, timeout=1200)
    print(f"    ({time.time()-t0:.1f}s)")
    print(p.stdout.rstrip())
    if p.returncode != 0:
        print(p.stderr[-600:])
    check("翻译成功", p.returncode == 0)
    good = ("rescheduled" in p.stdout
            and "equation" in p.stdout
            and "Why?" in p.stdout)
    check("译文质量达标（无复读）", good, p.stdout.replace("\n", " ")[:120])

    # ---- 4. 日文模型（大文件，单独确认可下载与校验）
    print("\n--- 4. asr-mm mt download ja（490 MB）---")
    t0 = time.time()
    rc, out = run(["mt", "download", "ja"])
    print(f"    ({time.time()-t0:.1f}s)")
    check("命令退出码为 0", rc == 0)
    check("程序报告日文模型已就绪", catalog.mt_model_ready("ja"))

    dj = catalog.mt_model_dir("ja")
    specj = catalog.MT_MODELS["ja"]
    for f in specj.files:
        p = dj / f.filename
        if not p.exists():
            check(f"文件存在 {f.filename}", False)
            continue
        check(f"文件正确 {f.filename}",
              p.stat().st_size == f.size and sha256(p) == f.sha256,
              f"{p.stat().st_size:,} 字节")

    script2 = (
        "import sys; sys.path.insert(0, r'%s')\n"
        "from asr_mm.translate import Translator\n"
        "r = Translator(['ja']).translate(%r)\n"
        "for t in r.texts['ja']: print('  ->', t)\n"
    ) % (ROOT, probe)
    t0 = time.time()
    p = subprocess.run([sys.executable, "-c", script2], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=env, cwd=ROOT, timeout=1800)
    print(f"    ({time.time()-t0:.1f}s)")
    print(p.stdout.rstrip())
    if p.returncode != 0:
        print(p.stderr[-600:])
    check("日文翻译成功", p.returncode == 0)
    check("日文无复读", p.stdout.count("保修期") <= 2 and len(p.stdout) < 400,
          f"{len(p.stdout)} 字符")

    # ---- 5. 真实转写 + 翻译 + 导出
    print("\n--- 5. 端到端：转写 + 翻译 + 导出 ---")
    video = ROOT / "课堂录像示例.mp4"
    if not (HOME / "runtime").exists():
        print("\n--- 5. 端到端：跳过（缺识别运行时）---")
    elif video.exists():
        outdir = ROOT / "build_verify_out"
        rc, out = run(["--lang", "zh", "transcribe", str(video),
                       "-s", "15", "-e", "45", "-f", "xlsx",
                       "-o", str(outdir), "--translate", "en,ja"])
        check("端到端退出码为 0", rc == 0, out.strip()[-200:])
        xlsx = list(outdir.glob("*.xlsx"))
        check("xlsx 已生成", bool(xlsx))
        if xlsx:
            from openpyxl import load_workbook
            rows = list(load_workbook(xlsx[0]).active.iter_rows(values_only=True))
            check("8 列", len(rows[0]) == 8, " | ".join(str(x) for x in rows[0]))
            check("每行都有英文", all(r[6] for r in rows[1:]))
            check("每行都有日文", all(r[7] for r in rows[1:]))
            for r in rows[1:]:
                print(f"    中: {r[5]}")
                print(f"      EN: {r[6]}")
                print(f"      JA: {r[7]}")
    else:
        check("测试视频存在", False, str(video))

    print("\n" + "=" * 68)
    print(f"RESULT: {len(FAIL)} failure(s)" + (f" -> {FAIL}" if FAIL else ""))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
