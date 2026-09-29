set -euo pipefail
cd /d/Work/asr_mm

echo "=== bash 语法检查 ==="
bash -n packaging/sign_macos.sh && echo "  sign_macos.sh OK"
bash -n packaging/notarize_macos.sh && echo "  notarize_macos.sh OK"

echo
echo "=== 生成的启动器语法检查 ==="
PYTHONIOENCODING=utf-8 python tools/check_launcher_syntax.py

echo
echo "=== workflow YAML 语法与步骤顺序 ==="
PYTHONIOENCODING=utf-8 python tools/check_workflow_order.py
