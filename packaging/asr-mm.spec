# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for asr-mm.

Build on the *target* OS — wheels, Qt plugins and executable formats are
platform specific, so there is no cross-compile path here.

    python packaging/prepare_payload.py --target win
    pyinstaller packaging/asr-mm.spec --noconfirm

Produces two runnable bundles:
    dist/asr-mm/      console build, the scripting / diagnostic entry point
    dist/asr-mm-gui/  windowed build, double-clickable
"""
import sys
from pathlib import Path

SPEC_DIR = Path(SPECPATH)
ROOT = SPEC_DIR.parent
PAYLOAD = SPEC_DIR / "payload"

sys.path.insert(0, str(ROOT))

block_cipher = None

# PySide6 pulls in a very large Qt tree. Nothing below is imported by asr-mm,
# and pruning it is the single biggest lever on bundle size.
EXCLUDED = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQuick3D", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtTest",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    "PySide6.QtSql", "PySide6.QtDBus", "PySide6.QtNetworkAuth",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
    "PySide6.QtSpatialAudio", "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech", "PySide6.QtVirtualKeyboard",
    "PySide6.QtHttpServer", "PySide6.QtSvgWidgets",
    # We stage ffmpeg.exe as a data file; letting imageio-ffmpeg ship its own
    # copy would put the same ~84 MB binary in the bundle twice.
    "imageio_ffmpeg",
    "tkinter", "unittest", "pydoc_data", "test", "lib2to3",
]


def payload_datas():
    """Staged read-only payload -> bundle root.

    The second element of a PyInstaller ``datas`` tuple is a *directory*, not a
    target filename. Passing the full relative path would nest the file one
    level deeper (``ffmpeg/ffmpeg.exe/ffmpeg.exe``) and leave a 1-byte stub at
    the expected path.

    ``asr_mm.paths`` looks for ``<_MEIPASS>/runtime`` and ``<_MEIPASS>/ffmpeg``,
    so the staging layout (``payload/runtime``, ``payload/ffmpeg``) is stripped
    here rather than changing the lookup code.
    """
    if not PAYLOAD.exists():
        raise SystemExit(
            "payload 尚未准备。请先运行:\n"
            "  python packaging/prepare_payload.py --target win")
    out = []
    for item in sorted(PAYLOAD.rglob("*")):
        if item.is_file():
            out.append((str(item), str(item.parent.relative_to(PAYLOAD))))
    return out


def build(script: str, name: str, console: bool, argv_emulation: bool):
    # Absolute: PyInstaller resolves script paths against SPECPATH, not the CWD.
    script_path = str(ROOT / script)
    a = Analysis(
        [script_path],
        pathex=[str(ROOT)],
        binaries=[],
        datas=payload_datas(),
        hiddenimports=[
            "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
            # HTTPS needs a CA bundle that survives freezing. Without certifi
            # a macOS build can end up with an empty trust store and reject
            # every certificate; truststore teaches OpenSSL to read the OS
            # keychain, which is where a corporate root certificate lives.
            "certifi", "truststore",
            # Excel export. openpyxl ships XML templates and a style table as
            # data files, and its submodules load lazily, so it needs both.
            "openpyxl", "openpyxl.cell._writer", "openpyxl.styles",
            "openpyxl.styles.numbers", "openpyxl.utils",
            "openpyxl.worksheet._writer", "openpyxl.workbook",
            # 翻译。ctranslate2 / sentencepiece 都是编译扩展，由 PyInstaller
            # 自带的 hook 收集，但 asr_mm.translate 是惰性 import 的，hook 看不到，
            # 所以显式点名。numpy 是 ctranslate2 的硬依赖。
            "ctranslate2", "ctranslate2.ext", "sentencepiece", "numpy",
        ],
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=EXCLUDED,
        noarchive=False,
    )
    pyz = PYZ(a.pure, a.zipped_data)
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        debug=False,
        strip=False,
        upx=False,
        console=console,
        disable_windowed_traceback=False,
        argv_emulation=argv_emulation,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    return COLLECT(exe, a.binaries, a.zipfiles, a.datas,
                   strip=False, upx=False, name=name)


build("asr_mm/launcher.py", "asr-mm", console=True, argv_emulation=False)
build("asr_mm/launcher_gui.py", "asr-mm-gui", console=False, argv_emulation=True)
