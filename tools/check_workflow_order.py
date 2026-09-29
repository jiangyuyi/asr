"""Check the release workflow: valid YAML and the macOS step order is correct.

Apple issues a notarisation ticket for the exact bytes submitted, so the order
must be sign -> package -> notarise. Getting it wrong produces a build that
fails Gatekeeper just as hard as an unsigned one, silently.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows" / "release.yml"

try:
    import yaml
except ImportError:
    print("  (pyyaml not installed, skipped)")
    raise SystemExit(0)

doc = yaml.safe_load(WF.read_text(encoding="utf-8"))
print("  YAML parses OK")

steps = doc["jobs"]["build"]["steps"]
names = [s.get("name", s.get("uses", "?")) for s in steps]
print("  steps:", " -> ".join(names))

problems = []
try:
    sign_i = names.index("Sign (macOS)")
    pack_i = names.index("Package archives")
    not_i = names.index("Notarise (macOS)")
except ValueError as exc:
    problems.append(f"missing step: {exc}")
else:
    if not sign_i < pack_i:
        problems.append("Sign must come before Package archives")
    if not not_i > pack_i:
        problems.append("Notarise must come after Package archives")
    print("  order: sign -> package -> notarise")

# The signing steps must be skippable so a build without secrets still works.
for name in ("Sign (macOS)", "Notarise (macOS)"):
    step = steps[names.index(name)]
    body = str(step.get("run", ""))
    if "exit 0" not in body:
        problems.append(f"{name} does not skip cleanly without secrets")

# Package must not use shell-specific syntax: windows-latest defaults to pwsh.
pack = steps[names.index("Package archives")]
pack_run = str(pack.get("run", ""))
if "set -euo" in pack_run or "[[" in pack_run:
    problems.append("Package archives uses bash-only syntax under PowerShell")
if "shell" in pack:
    problems.append("Package archives pins a shell; plain python is portable")

if problems:
    print()
    for p in problems:
        print(f"  [FAIL] {p}")
    raise SystemExit(1)
print("  all checks passed")
