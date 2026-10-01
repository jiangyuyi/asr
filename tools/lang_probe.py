# Measures what each model actually does with non-Chinese speech.
#
# SAPI ships one voice per language on this machine, so the same sentence can be
# synthesised in zh/ja/en and pushed through all three engines. That turns
# "should support it" into a number.
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\Work\asr_mm")
WORK = ROOT / "tools" / "lang_probe"
MODELS = ROOT / ".asrhome" / "models"
RUNTIME = ROOT / ".asrhome" / "runtime"
LOG = ROOT / "tools" / "lang_probe.txt"

SENTENCES = {
    "zh": "今天天气很好，我们去公园散步吧。",
    "ja": "今日はいい天気ですね、公園に行きましょう。",
    "en": "The weather is nice today, let's go to the park.",
}
VOICES = {"zh": "Microsoft Huihui Desktop",
          "ja": "Microsoft Haruka Desktop",
          "en": "Microsoft Zira Desktop"}

out: list[str] = []


def say(m=""):
    out.append(m)
    LOG.write_text("\n".join(out), encoding="utf-8")



import shutil  # noqa: E402
shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True)

# ---------------------------------------------------------------- synthesise
say("=" * 74)
say("LANGUAGE COVERAGE — what each model actually transcribes")
say("=" * 74)
say()

for lang, text in SENTENCES.items():
    wav = WORK / f"{lang}.wav"
    ps = f'''
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice("{VOICES[lang]}")
$s.SetOutputToWaveFile("{wav}")
$s.Speak("{text}")
$s.Dispose()
'''
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True)
    ok = wav.exists() and wav.stat().st_size > 1000
    say(f"[{'OK ' if ok else 'FAIL'}] synth {lang}: {wav.stat().st_size if ok else 0:,} bytes")
    if not ok:
        say("       " + r.stderr.decode("utf-8", "replace")[-200:])
say()

# ---------------------------------------------------------------- transcribe
sys.path.insert(0, str(ROOT))
from asr_mm import media  # noqa: E402

results: dict[str, dict[str, str]] = {}
for lang in SENTENCES:
    src = WORK / f"{lang}.wav"
    if not src.exists():
        continue
    wav16 = media.extract_audio(src, WORK / f"{lang}_16k.wav")
    results[lang] = {}
    for key, exe, model in (
        ("nano", "llama-funasr-cli.exe", None),
        ("paraformer", "llama-funasr-paraformer.exe", "paraformer-q8.gguf"),
        ("sensevoice", "llama-funasr-sensevoice.exe", "sensevoice-small-q8.gguf"),
    ):
        cmd = [str(RUNTIME / exe)]
        if key == "nano":
            cmd += ["--enc", str(MODELS / "funasr-encoder-f16.gguf"),
                    "-m", str(MODELS / "qwen3-0.6b-q4km.gguf")]
        else:
            cmd += ["-m", str(MODELS / model)]
        cmd += ["--vad", str(MODELS / "fsmn-vad.gguf"),
                "-a", str(wav16), "--vad-maxseg", "10000"]
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, timeout=600)
        text = r.stdout.decode("utf-8", "replace").strip()
        results[lang][key] = text.replace("\n", " ")[:150]
        say(f"  {lang} / {key:11s} ({time.time() - t0:.1f}s)")
        say(f"      in : {SENTENCES[lang]}")
        say(f"      out: {results[lang][key] or '(空)'}")
    say()

# ------------------------------------------------------------------- summary
say("=" * 74)
say("SUMMARY — empty output means the model cannot handle that language")
say("=" * 74)
for key in ("nano", "paraformer", "sensevoice"):
    cells = []
    for lang in SENTENCES:
        got = results.get(lang, {}).get(key, "")
        cells.append(f"{lang}:{'有输出' if got else '空'}")
    say(f"  {key:12s}  " + "   ".join(cells))
say()
(WORK / "results.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
say(f"raw results -> {WORK / 'results.json'}")
print("WROTE", LOG)
