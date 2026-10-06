"""PySide6 desktop UI: pick a time window on a video, transcribe it, edit, export.

Interface strings come from :mod:`asr_mm.i18n`. Switching language calls
``MainWindow.retranslate()``, which re-applies every visible string in place
rather than rebuilding the widgets, so the user's scroll position, selection and
any edits in the result table survive the switch.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings, QTime, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMenu, QMessageBox,
    QProgressBar, QPushButton, QSizePolicy, QSplitter,
    QTableWidget, QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget,
)

from .. import __version__, catalog, downloader, engine, media, transcribe
from ..i18n import available_languages, get_language, set_language, t
from ..srt import format_ts, render_srt, render_txt
from .loader import LoadProgressDialog, LoadWorker, PROBE_SHARE
from .range_slider import RangeSlider
from .worker import Job, TranscribeWorker, TranslateWorker

VIDEO_SUFFIXES = ("*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.m4v *.ts *.webm "
                  "*.mpg *.mpeg *.rmvb *.3gp")

# Result table columns. Translations are columns of their own rather than extra
# lines inside the text cell, so one utterance stays one row all the way into
# the workbook.
COL_START, COL_DUR, COL_TEXT, COL_EN, COL_JA = range(5)


def tc(seconds: float) -> str:
    return format_ts(max(0.0, seconds), comma=False)


def _is_black_pixmap(pix, threshold: int = 26) -> bool:
    """True when a frame carries essentially no image content.

    Sampled from a small scaled copy so this costs nothing even for 4K frames.
    Used to catch a poster that came back black instead of displaying a void.
    """
    small = pix.scaled(32, 32)
    img = small.toImage()
    lit = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixel(x, y)
            if (c >> 16 & 0xFF) > threshold or (c >> 8 & 0xFF) > threshold \
                    or (c & 0xFF) > threshold:
                lit += 1
    return lit < img.width() * img.height() * 0.02


class DropVideoLabel(QLabel):
    """Click-to-browse tile shown until a video is loaded."""

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setMinimumSize(480, 300)
        self.setStyleSheet(
            "border: 2px dashed #b9c0cc; border-radius: 10px;"
            "color:#6b7280; background:#fafbfc; font-size:15px;")
        self.setText(t("drop.hint"))

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()

    def dragEnterEvent(self, ev: QDragEnterEvent) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev: QDropEvent) -> None:
        for url in ev.mimeData().urls():
            if url.isLocalFile():
                p = url.toLocalFile()
                self.setToolTip(p)
                ev.acceptProposedAction()
                return


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.resize(1180, 800)

        self.video_path: Path | None = None
        self.info: media.MediaInfo | None = None
        self.result: transcribe.Transcript | None = None
        self.worker: TranscribeWorker | None = None
        self.tr_worker: TranslateWorker | None = None
        self._tr_inputs: tuple[list[str], list[str]] = ([], [])
        # target -> per-row translations, index aligned with result.segments
        self.translations: dict[str, list[str]] = {}
        self.loader: LoadWorker | None = None
        self._load_dialog: LoadProgressDialog | None = None
        self._pending_path: Path | None = None
        self.player_ok = False
        self._syncing = False
        self._poster_pixmap = None

        self._pos_timer = QTimer(self)
        self._pos_timer.setInterval(200)
        self._pos_timer.timeout.connect(self._tick_playhead)

        self.settings = QSettings("asr-mm", "asr-mm")
        stored = self.settings.value("lang", "")
        if stored:
            set_language(stored)
        self._build_ui()
        self._build_menu()
        self.retranslate()
        self._refresh_model_state()

    # ------------------------------------------------------------------- ui
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        # ---- top row: open + model + language
        top = QHBoxLayout()
        self.btn_open = QPushButton()
        self.btn_open.clicked.connect(self.choose_video)
        self.lbl_file = QLabel()
        self.lbl_file.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_file.setStyleSheet("color:#6b7280;")
        self.lbl_model_caption = QLabel()
        top.addWidget(self.btn_open)
        top.addWidget(self.lbl_file, 1)
        top.addWidget(self.lbl_model_caption)
        self.cmb_model = QComboBox()
        for spec in catalog.MODELS.values():
            self.cmb_model.addItem("", spec.key)
        self.cmb_model.setCurrentIndex(0)
        self.cmb_model.currentIndexChanged.connect(lambda _: self._refresh_model_state())
        top.addWidget(self.cmb_model)
        self.lbl_lang_caption = QLabel()
        top.addWidget(self.lbl_lang_caption)
        self.cmb_lang = QComboBox()
        for code, native in available_languages():
            self.cmb_lang.addItem(native, code)
        self.cmb_lang.setCurrentIndex(
            max(0, [c for c, _ in available_languages()].index(get_language())))
        self.cmb_lang.currentIndexChanged.connect(self._on_lang_changed)
        top.addWidget(self.cmb_lang)
        self.lbl_content_lang = QLabel()
        top.addWidget(self.lbl_content_lang)
        self.cmb_content = QComboBox()
        for code, key in (("auto", "lang.auto"), ("zh", "lang.zh"),
                          ("en", "lang.en"), ("ja", "lang.ja")):
            self.cmb_content.addItem(t(key), code)
        self.cmb_content.setCurrentIndex(0)
        self.cmb_content.setToolTip(t("cli.content_lang.help"))
        self.cmb_content.currentIndexChanged.connect(
            lambda _: self._refresh_model_state())
        top.addWidget(self.cmb_content)
        root.addLayout(top)

        # ---- middle: preview | controls
        split = QSplitter(Qt.Horizontal)

        left = QWidget()
        # 预览区按 4:3 限宽。放任它随窗口横向拉长的话，4:3 的封面/画面只占
        # 中间一小条，两侧全是底色——最大化窗口时那两侧比画面本身大得多，
        # 看起来就像黑屏。
        left.setMaximumWidth(760)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.drop = DropVideoLabel()
        self.drop.clicked.connect(self.choose_video)
        # 只占自身最小宽度并水平居中：让它横向铺满的话，4:3 的封面在两侧留出
        # 一大片底色，看起来就像黑屏。
        ll.addWidget(self.drop, 0, Qt.AlignHCenter)

        # QVideoWidget 自己**不能加样式表**。Qt 的 QStyleSheetStyle 会接管
        # 绘制，把原生视频表面挡住，结果就是一个纯黑矩形——解码明明在跑
        # （position 在涨），屏幕上却什么都没有。圆角边框放到外层容器上。
        self.video_frame = QFrame()
        self.video_frame.setStyleSheet(
            "QFrame#videoFrame{background:#000;border-radius:8px;}")
        vf = QVBoxLayout(self.video_frame)
        vf.setContentsMargins(0, 0, 0, 0)
        self.video = QVideoWidget()
        self.video.setMinimumSize(480, 300)
        self.video.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vf.addWidget(self.video)
        self.video_frame.hide()
        # 撑满左栏。之前 addStretch(1) 把它挤在顶部、下面留一大片空白，
        # 4:3 的视频被缩成窄条，看着像没在播。
        ll.addWidget(self.video_frame, 1)
        split.addWidget(left)

        right = QWidget()
        right.setMaximumWidth(340)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)

        self.sec_range = self._section("")
        rl.addWidget(self.sec_range)
        self.slider = RangeSlider()
        self.slider.startMoved.connect(lambda v: self._set_time(self.spin_start, v))
        self.slider.endMoved.connect(lambda v: self._set_time(self.spin_end, v))
        self.slider.rangeChanged.connect(self._on_range_changed)
        rl.addWidget(self.slider)

        form = QFormLayout()
        self.lbl_start = QLabel()
        self.lbl_end = QLabel()
        self.spin_start = QTimeEdit()
        self.spin_end = QTimeEdit()
        for s in (self.spin_start, self.spin_end):
            s.setDisplayFormat("HH:mm:ss.zzz")
            s.setEnabled(False)
        self.spin_start.timeChanged.connect(self._on_spin_changed)
        self.spin_end.timeChanged.connect(self._on_spin_changed)
        self.btn_set_start = QPushButton()
        self.btn_set_start.clicked.connect(lambda: self._set_range_from_player(0))
        self.btn_set_end = QPushButton()
        self.btn_set_end.clicked.connect(lambda: self._set_range_from_player(1))
        self.btn_set_start.setEnabled(False)
        self.btn_set_end.setEnabled(False)
        self._range_buttons = (self.btn_set_start, self.btn_set_end)

        row = QHBoxLayout()
        row.addWidget(self.btn_set_start)
        row.addWidget(self.btn_set_end)
        form.addRow(self.lbl_start, self.spin_start)
        form.addRow(self.lbl_end, self.spin_end)
        form.addRow("", row)

        self.btn_play = QPushButton()
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_play.setEnabled(False)
        form.addRow("", self.btn_play)
        rl.addLayout(form)

        self.sec_options = self._section("")
        rl.addWidget(self.sec_options)
        self.lbl_preroll = QLabel()
        self.spin_preroll = QDoubleSpinBox()
        self.spin_preroll.setRange(0.0, 5.0)
        self.spin_preroll.setSingleStep(0.1)
        self.spin_preroll.setValue(0.0)
        self.chk_drop = QCheckBox()
        self.chk_loud = QCheckBox()
        f2 = QFormLayout()
        f2.addRow(self.lbl_preroll, self.spin_preroll)
        f2.addRow("", self.chk_drop)
        f2.addRow("", self.chk_loud)
        rl.addLayout(f2)

        self.lbl_model_state = QLabel()
        self.lbl_model_state.setWordWrap(True)
        self.lbl_model_state.setStyleSheet("color:#6b7280; font-size:12px;")
        rl.addWidget(self.lbl_model_state)

        self.btn_run = QPushButton()
        self.btn_run.setMinimumHeight(42)
        self.btn_run.setStyleSheet(
            "QPushButton{background:#3b82f6;color:white;font-size:15px;font-weight:600;"
            "border:none;border-radius:8px;}QPushButton:disabled{background:#9ca3af;}")
        self.btn_run.clicked.connect(self.run_transcribe)
        self.btn_run.setEnabled(False)
        rl.addWidget(self.btn_run)
        rl.addStretch(1)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 3)

        # ---- results
        self.sec_results = self._section("")

        # Translation controls sit directly above the table they fill. The
        # checkboxes double as the availability indicator: an unchecked box
        # means the model is not downloaded, and the button says so on click.
        trow = QHBoxLayout()
        trow.setSpacing(8)
        self.lbl_tr_pick = QLabel()
        trow.addWidget(self.lbl_tr_pick)
        self.chk_tr = {}
        for code in ("en", "ja"):
            box = QCheckBox()
            box.setChecked(True)
            self.chk_tr[code] = box
            trow.addWidget(box)
        self.btn_translate = QPushButton()
        self.btn_translate.clicked.connect(self.run_translate)
        self.btn_translate.setEnabled(False)
        trow.addWidget(self.btn_translate)
        self.btn_tr_cancel = QPushButton()
        self.btn_tr_cancel.clicked.connect(self.cancel_translate)
        self.btn_tr_cancel.hide()
        trow.addWidget(self.btn_tr_cancel)
        trow.addStretch(1)
        root.addWidget(self.sec_results)
        root.addLayout(trow)

        self.table = QTableWidget(0, 5)
        self.table.setColumnWidth(0, 100)
        self.table.setColumnWidth(1, 70)
        for col in (COL_TEXT, COL_EN, COL_JA):
            self.table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.DoubleClicked
                                    | QTableWidget.EditKeyPressed
                                    | QTableWidget.AnyKeyPressed)
        root.addWidget(self.table, 2)

        # ---- bottom bar
        bottom = QHBoxLayout()
        self.btn_copy = QPushButton()
        self.btn_copy.clicked.connect(self.copy_text)
        self.btn_save = QPushButton()
        self.btn_save.clicked.connect(self.export)
        self.btn_clip = QPushButton()
        self.btn_clip.clicked.connect(self.export_clip)
        for b in (self.btn_copy, self.btn_save, self.btn_clip):
            b.setEnabled(False)
        bottom.addWidget(self.btn_copy)
        bottom.addWidget(self.btn_save)
        bottom.addWidget(self.btn_clip)
        bottom.addStretch(1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(200)
        self.progress.hide()
        bottom.addWidget(self.progress)
        root.addLayout(bottom)

        self.setCentralWidget(central)
        self.setAcceptDrops(True)

        self.player = QMediaPlayer(self)
        self.player.setVideoOutput(self.video)
        self.audio_out = QAudioOutput(self)
        self.audio_out.setVolume(1.0)
        self.player.setAudioOutput(self.audio_out)
        self.player.positionChanged.connect(self._on_position)
        self.player.errorOccurred.connect(self._on_player_error)
        # 播放状态变化时按钮文案要跟着变：点播放之后唯一按过的控件不给反馈，
        # 用户会以为没点上。
        self.player.playbackStateChanged.connect(
            lambda _s: self._sync_play_button())
        # 按下播放后 3 秒还在原地 -> 判定为「画面这条路不通」，给出提示
        self._play_mark = 0
        self._playing_started = False
        self._play_watch = QTimer(self)
        self._play_watch.setSingleShot(True)
        self._play_watch.setInterval(3000)
        self._play_watch.timeout.connect(self._on_play_watch)

    def _section(self, title: str) -> QLabel:
        lab = QLabel(title)
        lab.setStyleSheet("font-weight:600; color:#374151; padding-top:6px;")
        return lab

    def _build_menu(self) -> None:
        self.menu_file = self.menuBar().addMenu("")
        self.act_open = QAction(self)
        self.act_open.setShortcut(QKeySequence.Open)
        self.act_open.triggered.connect(self.choose_video)
        self.menu_file.addAction(self.act_open)
        self.menu_file.addSeparator()
        self.act_quit = QAction(self)
        self.act_quit.setShortcut(QKeySequence.Quit)
        self.act_quit.triggered.connect(self.close)
        self.menu_file.addAction(self.act_quit)

        self.menu_tools = self.menuBar().addMenu("")
        self.act_download = QAction(self)
        self.act_download.triggered.connect(self.download_models)
        self.menu_tools.addAction(self.act_download)
        self.act_download_mt = QAction(self)
        self.act_download_mt.triggered.connect(self.download_mt_models)
        self.menu_tools.addAction(self.act_download_mt)
        self.act_open_models = QAction(self)
        self.act_open_models.triggered.connect(self.open_models_dir)
        self.menu_tools.addAction(self.act_open_models)
        self.act_net = QAction(self)
        self.act_net.triggered.connect(self.network_settings)
        self.menu_tools.addAction(self.act_net)
        self.act_doctor = QAction(self)
        self.act_doctor.triggered.connect(self.doctor)
        self.menu_tools.addAction(self.act_doctor)

        self.menu_help = self.menuBar().addMenu("")
        self.act_about = QAction(self)
        self.act_about.triggered.connect(self.about)
        self.menu_help.addAction(self.act_about)

    # ------------------------------------------------------------ retranslate
    def retranslate(self) -> None:
        """Re-apply every visible string in the active language."""
        if not hasattr(self, "table"):
            return
        self.setWindowTitle(t("app.title", version=__version__))
        self.btn_open.setText(t("toolbar.open"))
        self.lbl_model_caption.setText(t("toolbar.model"))
        self.lbl_lang_caption.setText(t("toolbar.language"))
        self.lbl_content_lang.setText(t("lang.caption"))
        self.cmb_content.setItemText(0, t("lang.auto"))
        self.cmb_content.setItemText(1, t("lang.zh"))
        self.cmb_content.setItemText(2, t("lang.en"))
        self.cmb_content.setItemText(3, t("lang.ja"))
        self.cmb_content.setToolTip(t("cli.content_lang.help"))
        self.cmb_model.setItemText(0, t("model.nano"))
        self.cmb_model.setItemText(1, t("model.paraformer"))
        self.cmb_model.setItemText(2, t("model.sensevoice"))
        self.cmb_model.setToolTip(t("model.nano.note"))

        self.sec_range.setText(t("section.range"))
        self.lbl_start.setText(t("range.start"))
        self.lbl_end.setText(t("range.end"))
        self.btn_set_start.setText(t("range.set_start"))
        self.btn_set_end.setText(t("range.set_end"))
        self.btn_play.setText(t("play"))
        self.sec_options.setText(t("section.options"))
        self.lbl_preroll.setText(t("opt.preroll"))
        self.spin_preroll.setSuffix(t("opt.preroll_suffix"))
        self.spin_preroll.setToolTip(t("opt.preroll_tip"))
        self.chk_drop.setText(t("opt.drop_short"))
        self.chk_drop.setToolTip(t("opt.drop_short_tip"))
        self.chk_loud.setText(t("opt.loudnorm"))
        self.chk_loud.setToolTip(t("opt.loudnorm_tip"))
        self.btn_run.setText(t("run"))
        self.sec_results.setText(t("section.results"))
        self.lbl_tr_pick.setText(t("translate.pick"))
        for code, box in self.chk_tr.items():
            box.setText(t("mt." + code))
            box.setToolTip(t("mt." + code + ".note"))
        self.btn_translate.setText(t("action.translate"))
        self.btn_tr_cancel.setText(t("load.cancel"))
        self.table.setHorizontalHeaderLabels([t("table.col_start"),
                                              t("table.col_dur"),
                                              t("table.col_text"),
                                              t("table.col_en"),
                                              t("table.col_ja")])
        self.btn_copy.setText(t("action.copy"))
        self.btn_save.setText(t("action.export"))
        self.btn_clip.setText(t("action.export_clip"))

        self.menu_file.setTitle(t("menu.file"))
        self.act_open.setText(t("menu.open"))
        self.act_quit.setText(t("menu.quit"))
        self.menu_tools.setTitle(t("menu.tools"))
        self.act_download.setText(t("menu.download_models"))
        self.act_download_mt.setText(t("menu.download_mt"))
        self.act_open_models.setText(t("menu.open_models"))
        self.act_net.setText(t("net.title"))
        self.act_doctor.setText(t("menu.doctor"))
        self.menu_help.setTitle(t("menu.help"))
        self.act_about.setText(t("menu.about"))

        if self.drop.pixmap() is None or self._poster_pixmap is None:
            self.drop.setText(t("drop.hint"))
        self._refresh_file_label()
        self._refresh_model_state()

    def _on_lang_changed(self, index: int) -> None:
        code = self.cmb_lang.itemData(index)
        if not code or code == get_language():
            return
        set_language(code)
        self.settings.setValue("lang", code)
        self.retranslate()
        self.statusBar().showMessage(t("status.ready"))

    # ----------------------------------------------------------------- video
    def _refresh_file_label(self) -> None:
        if not (self.video_path and self.info):
            self.lbl_file.setText("—")
            return
        self.lbl_file.setText(f"{self.video_path.name}   "
                              f"({tc(self.info.duration)} · "
                              f"{self.info.size_mb:.0f} {t('units.mb_short')} · "
                              f"{self.info.audio_codec})")
        self.lbl_file.setToolTip(str(self.video_path))

    def choose_video(self) -> None:
        start = self.settings.value("last_dir", "")
        path, _ = QFileDialog.getOpenFileName(
            self, t("filedialog.video"), start, t("filter.video"))
        if path:
            self.load_video(Path(path))

    def load_video(self, path: Path) -> None:
        """Start a background load; the window stays live until it lands."""
        if self.loader is not None and self.loader.isRunning():
            self.loader.cancel()
            self.loader.wait(3000)
        self._pending_path = path
        self.settings.setValue("last_dir", str(path.parent))

        dlg = LoadProgressDialog(t("load.title"), t("load.cancel"), 0, 100, self)
        dlg.setWindowTitle(t("load.window"))
        dlg.setWindowModality(Qt.WindowModal)
        # A fast local file loads in ~200 ms; without a minimum duration the
        # dialog would flash in and out. Anything slower still shows it.
        dlg.setMinimumDuration(350)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        # Indeterminate while probing: we have no honest percentage to show yet,
        # and a bar stuck at 2% reads exactly like a hang. The decode phase
        # switches to a real percentage.
        dlg.setRange(0, 0)
        dlg.setLabelText(t("load.probing", name=path.name))
        self._load_dialog = dlg

        # ffmpeg reports progress in bursts, so drive the visible value from a
        # timer that eases toward the real one — the bar then moves smoothly
        # instead of jumping 18% -> 100%.
        state = {"target": 0.0, "shown": 0.0, "determinate": False}
        smoother = QTimer(dlg)
        smoother.setInterval(40)

        def ease() -> None:
            if not state["determinate"]:
                return
            delta = state["target"] - state["shown"]
            if abs(delta) < 1.0:
                state["shown"] = state["target"]
                smoother.stop()
            else:
                state["shown"] += delta * 0.3
            dlg.setValue(int(state["shown"]))

        smoother.timeout.connect(ease)

        worker = LoadWorker(str(path), self)
        self.loader = worker

        def on_progress(frac: float, key: str) -> None:
            if self._load_dialog is None:
                return
            dlg.setLabelText(t(key, name=path.name))
            if not state["determinate"] and frac > PROBE_SHARE:
                state["determinate"] = True
                dlg.setRange(0, 100)
                dlg.setValue(0)
            state["target"] = frac * 100.0
            if state["determinate"] and not smoother.isActive():
                smoother.start()

        def stop_smoother() -> None:
            smoother.stop()

        def on_done(loaded) -> None:
            stop_smoother()
            self._close_load_dialog()
            self.loader = None
            self._apply_loaded(loaded)

        def on_failed(msg: str) -> None:
            stop_smoother()
            self._close_load_dialog()
            self.loader = None
            QMessageBox.critical(self, t("dlg.cannot_open"), msg)

        def on_cancel() -> None:
            # closeEvent() also raises this, so only act while the worker is
            # genuinely still running.
            if not worker.isRunning():
                return
            worker.cancel()
            stop_smoother()
            self._close_load_dialog()
            self.statusBar().showMessage(t("load.cancelled", name=path.name))
            # Hold the reference until the thread really ends: dropping it here
            # would let the QThread be collected while still running. The
            # identity check keeps a stale worker from clearing a newer one.
            def release(w=worker) -> None:
                if self.loader is w:
                    self.loader = None

            worker.finished.connect(release)

        dlg.cancelRequested.connect(on_cancel)
        worker.progress.connect(on_progress)
        worker.done.connect(on_done)
        worker.failed.connect(on_failed)
        worker.start()
        dlg.open()

    def _close_load_dialog(self) -> None:
        dlg, self._load_dialog = self._load_dialog, None
        if dlg is not None:
            dlg.reset()
            dlg.close()
            dlg.deleteLater()

    def _apply_loaded(self, loaded) -> None:
        """Everything that used to happen synchronously in load_video()."""
        path, info = loaded.path, loaded.info
        self.video_path, self.info = path, info
        self.result = None
        self.translations = {}
        self.table.setRowCount(0)
        for b in (self.btn_copy, self.btn_save, self.btn_clip):
            b.setEnabled(False)
        self._refresh_translate_state()
        self._refresh_file_label()

        self.slider.setDuration(info.duration)
        self.slider.setRange(0.0, info.duration)
        self._sync_spins(0.0, info.duration)
        for s in (self.spin_start, self.spin_end):
            s.setEnabled(True)
        for b in self._range_buttons:
            b.setEnabled(True)
        self.btn_run.setEnabled(True)

        # Show the poster straight away so the window is never a black slab
        # while the platform player works out the format.
        if loaded.poster is not None:
            self._show_poster(loaded.poster)
        else:
            self._show_preview_video()
        # 海报先留着，等真的开始播了再撤掉。原来 setSource 之后就撤，
        # 万一视频表面没画出来，用户看到的就是一个纯黑矩形，没有任何提示。
        self._playing_started = False
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        QTimer.singleShot(1200, lambda: self._confirm_playback(path))
        self.statusBar().showMessage(
            t("status.loaded", name=path.name, duration=tc(info.duration)))

    def _confirm_playback(self, path: Path) -> None:
        if self.video_path != path:
            return
        if self.player.error() != QMediaPlayer.Error.NoError:
            # The poster the loader already grabbed becomes the preview; no
            # extra work is needed here.
            self.player_ok = False
            if self._poster_pixmap is None:
                self._show_poster(path)
            self.statusBar().showMessage(
                t("status.preview_failed", error=self.player.errorString()))
            self.btn_play.setEnabled(False)
        else:
            self.player_ok = True
            self.btn_play.setEnabled(True)
            # 故意**不**在这里撤海报：只有确认画面真的在动才撤。
            if self._poster_pixmap is not None:
                self._show_preview_poster()
            else:
                self._show_preview_video()

    # 预览区在「海报」和「播放」两种内容之间切换。两个都要**整体**切换：
    # 只藏里面的 QVideoWidget 的话，外层容器的底色会露在下面，多出一整块黑色。
    def _show_preview_poster(self) -> None:
        self.video_frame.hide()
        self.drop.show()

    def _show_preview_video(self) -> None:
        self.drop.hide()
        self.video_frame.show()
        self.video.show()

    def _hide_poster(self) -> None:
        """Swap the poster back out once the player takes over."""
        if self._poster_pixmap is not None:
            self._show_preview_video()

    def _show_poster(self, poster: Path) -> None:
        """Display a poster frame in place of (or behind) the video widget."""
        from PySide6.QtGui import QPixmap
        pix = QPixmap(str(poster))
        if pix.isNull():
            return
        if _is_black_pixmap(pix):
            # A black poster is worse than no poster: it reads as "the app is
            # broken". Keep the hint tile and say so instead of showing a void.
            self._poster_pixmap = None
            self.video_frame.hide()
            # 顺序要紧：setPixmap(空) 会把 QLabel 的文字一起清掉，
            # 所以先清 pixmap 再写提示文字。
            self.drop.setPixmap(QPixmap())
            self.drop.setText(t("drop.hint"))
            self.drop.setStyleSheet(
                "border: 2px dashed #b9c0cc; border-radius: 10px;"
                "color:#6b7280; background:#fafbfc; font-size:15px;")
            self.drop.show()
            self.statusBar().showMessage(t("status.poster_black"))
            return
        self._poster_pixmap = pix
        self.video_frame.hide()
        self.drop.setText("")
        self.drop.setPixmap(pix.scaled(
            self.drop.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        # 深灰而不是纯黑：4:3 的封面在宽屏里只占中间一小条，纯黑底会让
        # 整个预览区读起来像"黑屏"，深灰能让"有没有画面"一眼可辨。
        self.drop.setStyleSheet("border-radius:10px; background:#20242b;")
        self.drop.show()

    def _toggle_play(self) -> None:
        if not self.player_ok:
            return
        # play()/pause() 是异步的，此刻查 playbackState() 还可能是旧值，
        # 所以按「意图」先设文案，playbackStateChanged 到达时再校正。
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self._set_play_label(False)
            self._play_watch.stop()
        else:
            self.player.play()
            self._set_play_label(True)
            self._play_mark = self.player.position()
            self._play_watch.start()

    def _on_play_watch(self) -> None:
        """按了播放但播放头没动 —— 说明画面这条路真的不通。

        这种情况以前只是留一个黑矩形加一个看着没反应的按钮。现在明确
        告诉用户，并把海报放回去，至少还能看到视频内容。
        """
        if self.player.position() > self._play_mark + 200:
            return                       # 已经在正常走了，只是这次回调晚了
        self.player.pause()
        self._set_play_label(False)
        if self._poster_pixmap is not None:
            self._show_preview_poster()
        self.statusBar().showMessage(t("status.preview_stuck"))

    def _set_play_label(self, playing: bool) -> None:
        self.btn_play.setText(t("pause") if playing else t("play"))
        self.btn_play.setToolTip(t("pause") if playing else t("play"))

    def _sync_play_button(self) -> None:
        """Correct the label from the real state (playback ended, error, …)."""
        playing = (self.player.playbackState()
                   == QMediaPlayer.PlaybackState.PlayingState)
        if not playing:
            self._play_watch.stop()
        self._set_play_label(playing)

    def _on_position(self, pos: int) -> None:
        self.slider.setPlayhead(pos / 1000.0)
        if not self._syncing:
            self.statusBar().showMessage(t("status.position", tc=tc(pos / 1000.0)))
        # 播放头真的动了 -> 画面这条路通，撤掉海报露出视频
        if pos > self._play_mark + 200:
            self._play_mark = pos
            if not self._playing_started:
                self._playing_started = True
                self._play_watch.stop()
                self._hide_poster()

    def _tick_playhead(self) -> None:
        if (self.player_ok
                and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState):
            self.statusBar().showMessage(
                t("status.position", tc=tc(self.player.position() / 1000.0)))

    def _on_player_error(self, *args) -> None:
        self.player_ok = False

    # ---------------------------------------------------------------- range
    def _set_time(self, spin: QTimeEdit, seconds: float) -> None:
        self._syncing = True
        spin.setTime(QTime(0, 0).addMSecs(int(round(seconds * 1000))))
        self._syncing = False

    def _sync_spins(self, start: float, end: float) -> None:
        self._set_time(self.spin_start, start)
        self._set_time(self.spin_end, end)

    def _on_spin_changed(self) -> None:
        if self._syncing or not self.info:
            return
        self._syncing = True
        self.slider.setRange(self._spin_secs(self.spin_start), self._spin_secs(self.spin_end))
        self._syncing = False

    @staticmethod
    def _spin_secs(spin: QTimeEdit) -> float:
        t_ = spin.time()
        return (t_.hour() * 3600 + t_.minute() * 60 + t_.second()
                + t_.msec() / 1000.0)

    def _on_range_changed(self, start: float, end: float) -> None:
        if self._syncing:
            return
        self._sync_spins(start, end)

    def _set_range_from_player(self, which: int) -> None:
        pos = self.player.position() / 1000.0
        start, end = self.slider.range()
        if which == 0:
            self.slider.setRange(min(pos, end - 0.1), end)
            self.statusBar().showMessage(t("status.start_set", tc=tc(pos)))
        else:
            self.slider.setRange(start, max(pos, start + 0.1))
            self.statusBar().showMessage(t("status.end_set", tc=tc(pos)))
        if self.player_ok:
            self.player.setPosition(int(pos * 1000))

    def _current_range(self) -> tuple[str, str]:
        return (self.spin_start.time().toString("HH:mm:ss.zzz"),
                self.spin_end.time().toString("HH:mm:ss.zzz"))

    # ---------------------------------------------------------------- model
    def _refresh_model_state(self) -> None:
        key = self.cmb_model.currentData()
        try:
            spec = catalog.resolve_model(key)
        except KeyError:
            return
        missing = downloader.missing_files(spec)
        lines = []
        if missing:
            names = "、".join(m.filename for m in missing[:2])
            lines.append(t("model.missing", count=len(missing), names=names))
        else:
            lines.append(t("model.ready", key=spec.key,
                           size=downloader.human(sum(f.size for f in spec.files))))

        content = self.cmb_content.currentData() if hasattr(self, "cmb_content") else "auto"
        unsupported = spec.warning_for(content)
        if unsupported:
            lines.append("⚠ " + unsupported)
        elif content in spec.degraded:
            lines.append("⚠ " + t("lang.degraded", model=spec.key,
                                  lang=t("lang." + content)))
        self.lbl_model_state.setText("\n".join(lines))
        self.lbl_model_state.setStyleSheet(
            "color:#b45309; font-size:12px;" if unsupported
            else "color:#6b7280; font-size:12px;")
        if self.worker is None:
            self.btn_run.setEnabled(bool(self.video_path) and not missing)

    def download_models(self) -> None:
        from .model_dialog import ModelDownloadDialog
        dlg = ModelDownloadDialog(self)
        dlg.exec()
        self._refresh_model_state()
        self._refresh_translate_state()

    def download_mt_models(self) -> None:
        from .mt_dialog import MtDownloadDialog
        dlg = MtDownloadDialog(self)
        dlg.exec()
        self._refresh_translate_state()

    def open_models_dir(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from .. import paths
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.models_dir())))

    def network_settings(self) -> None:
        from .net_dialog import NetworkSettingsDialog
        dlg = NetworkSettingsDialog(self)
        dlg.exec()
        self._refresh_model_state()

    def doctor(self) -> None:
        from .. import paths
        lines = [f"{k}: {v}" for k, v in paths.describe_layout().items()]
        rt = downloader.runtime_status()
        lines.insert(0, t("cli.doctor.runtime") + ": "
                     + (t("cli.status_ready") if rt["ready"] else t("cli.status_missing")))
        QMessageBox.information(self, t("cli.doctor.title", version=__version__),
                                "\n".join(lines))

    def about(self) -> None:
        QMessageBox.about(
            self, t("menu.about"),
            t("dlg.about", version=__version__, hint=t("dlg.about_hint")))

    # ------------------------------------------------------------------ run
    def run_transcribe(self) -> None:
        if not self.video_path or self.worker is not None:
            return
        key = self.cmb_model.currentData()
        if not downloader.is_model_ready(key):
            QMessageBox.warning(self, t("menu.about"),
                                t("dlg.model_missing", key=key))
            return
        content = self.cmb_content.currentData()
        warning = catalog.resolve_model(key).warning_for(content)
        if warning:
            QMessageBox.warning(self, t("run"), warning)
        start, end = self._current_range()
        self.btn_run.setEnabled(False)
        self.progress.show()
        self.statusBar().showMessage(t("status.running"))
        job = Job(video=str(self.video_path), start=start, end=end, model=key,
                  preroll=self.spin_preroll.value(),
                  drop_short=self.chk_drop.isChecked(),
                  loudnorm=self.chk_loud.isChecked(),
                  maxseg=engine.DEFAULT_MAXSEG_MS)
        self.worker = TranscribeWorker(job, self)
        self.worker.stage.connect(
            lambda msg: self.statusBar().showMessage(
                t("status.extract") if "抽取" in msg or "xtract" in msg.lower()
                else t("status.running")))
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_done(self, result: transcribe.Transcript) -> None:
        self.worker = None
        self.result = result
        self.translations = {}
        self.progress.hide()
        self.btn_run.setEnabled(True)
        self._fill_table(result)
        for b in (self.btn_copy, self.btn_save, self.btn_clip):
            b.setEnabled(True)
        self._refresh_translate_state()
        speed = f"{1 / result.rtf:.0f}×" if result.rtf else "—"
        fmt = t("status.done", count=len(result.segments),
                elapsed=f"{result.elapsed:.1f}", audio=f"{result.audio_seconds:.0f}",
                speed=speed)
        if result.warning:
            fmt = t("status.done_note", count=len(result.segments),
                    elapsed=f"{result.elapsed:.1f}",
                    audio=f"{result.audio_seconds:.0f}", speed=speed,
                    note=result.warning)
        self.statusBar().showMessage(fmt)

    def _on_failed(self, msg: str) -> None:
        self.worker = None
        self.progress.hide()
        self.btn_run.setEnabled(True)
        self.statusBar().showMessage(t("status.failed"))
        QMessageBox.critical(self, t("dlg.transcribe_failed"), msg)

    def _fill_table(self, result: transcribe.Transcript) -> None:
        self.table.setRowCount(len(result.segments))
        for row, seg in enumerate(result.segments):
            t0 = QTableWidgetItem(tc(seg.start))
            t1 = QTableWidgetItem(f"{seg.duration:.1f}s")
            t2 = QTableWidgetItem(seg.text)
            t2.setToolTip(t("row.tip_suspect") if seg.suspicious else t("row.tip"))
            if seg.suspicious:
                t2.setBackground(Qt.GlobalColor.yellow)
            cells = {COL_START: t0, COL_DUR: t1, COL_TEXT: t2}
            for code, col in (("en", COL_EN), ("ja", COL_JA)):
                text = self.translations.get(code, [])
                item = QTableWidgetItem(text[row] if row < len(text) else "")
                item.setToolTip(t("row.tip_translation"))
                cells[col] = item
            for col, item in cells.items():
                if col in (COL_START, COL_DUR):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)
        self.table.resizeRowsToContents()

    # ------------------------------------------------------------- translate
    def _selected_targets(self) -> list[str]:
        return [c for c, box in self.chk_tr.items() if box.isChecked()]

    def _refresh_translate_state(self) -> None:
        """Enable the button only when there is text and a target, and mark
        the boxes whose model is still missing."""
        ready = self.result is not None and self.table.rowCount() > 0
        for code, box in self.chk_tr.items():
            have = catalog.mt_model_ready(code)
            box.setEnabled(ready and not self._tr_busy)
            font = box.font()
            font.setStrikeOut(not have)
            box.setFont(font)
        targets = self._selected_targets()
        missing = [c for c in targets if not catalog.mt_model_ready(c)]
        enabled = (ready and bool(targets) and not missing
                   and self.tr_worker is None)
        self.btn_translate.setEnabled(enabled)
        self.btn_translate.setToolTip(
            t("dlg.mt_missing", targets="、".join(
                catalog.MT_MODELS[c].target for c in missing))
            if missing else "")

    @property
    def _tr_busy(self) -> bool:
        return self.tr_worker is not None

    def run_translate(self) -> None:
        if self.tr_worker is not None:
            return
        segs = self._current_segments()
        if not segs:
            self.statusBar().showMessage(t("warn.no_translation"))
            return
        targets = self._selected_targets()
        if not targets:
            self.statusBar().showMessage(t("err.mt_no_target"))
            return
        missing = [c for c in targets if not catalog.mt_model_ready(c)]
        if missing:
            QMessageBox.warning(
                self, t("dlg.translate_failed"),
                t("dlg.mt_missing", targets="、".join(
                    catalog.MT_MODELS[c].target for c in missing)))
            return

        texts = [s.text for s in segs]
        self.btn_translate.hide()
        self.btn_tr_cancel.show()
        self.progress.show()
        self.statusBar().showMessage(t("status.translating", done=0, total=len(texts)))
        self.tr_worker = TranslateWorker(texts, targets, self)
        self.tr_worker.progress.connect(
            lambda code, done, total: self.statusBar().showMessage(
                t("status.translating", done=done, total=total)))
        self.tr_worker.finished_ok.connect(self._on_translated)
        self.tr_worker.failed.connect(self._on_translate_failed)
        self._tr_inputs = (texts, targets)
        self.tr_worker.start()

    def cancel_translate(self) -> None:
        if self.tr_worker is not None:
            self.tr_worker.cancel()
            self.statusBar().showMessage(t("err.mt_cancelled"))

    def _on_translated(self, result) -> None:
        texts, targets = getattr(self, "_tr_inputs", ([], []))
        self.tr_worker = None
        self._tr_inputs = ([], [])
        self.progress.hide()
        self.btn_tr_cancel.hide()
        self.btn_translate.show()
        for code in targets:
            values = result.texts.get(code) or []
            self.translations[code] = values
            col = COL_EN if code == "en" else COL_JA
            for row in range(self.table.rowCount()):
                item = self.table.item(row, col)
                if item is not None:
                    item.setText(values[row] if row < len(values) else "")
        self.table.resizeRowsToContents()
        langs = "、".join(t("mt." + c) for c in targets)
        self.statusBar().showMessage(t(
            "status.translated", langs=langs, count=len(texts),
            elapsed=f"{result.elapsed:.1f}"))
        self._refresh_translate_state()

    def _on_translate_failed(self, msg: str) -> None:
        self.tr_worker = None
        self._tr_inputs = ([], [])
        self.progress.hide()
        self.btn_tr_cancel.hide()
        self.btn_translate.show()
        self.statusBar().showMessage(t("status.translate_failed"))
        self._refresh_translate_state()
        QMessageBox.critical(self, t("dlg.translate_failed"), msg)

    def _current_translations(self) -> dict | None:
        """Translations as the table currently shows them, so a hand-fixed
        cell is what gets exported."""
        out: dict[str, list[str]] = {}
        for code, col in (("en", COL_EN), ("ja", COL_JA)):
            values = []
            for row in range(self.table.rowCount()):
                item = self.table.item(row, col)
                values.append(item.text() if item else "")
            if any(v.strip() for v in values):
                out[code] = values
        return out or None

    def _on_row_selected(self) -> None:
        row = self.table.currentRow()
        if self.result and 0 <= row < len(self.result.segments) and self.player_ok:
            self.player.setPosition(int(self.result.segments[row].start * 1000))
            self.player.play()

    def _current_segments(self) -> list:
        """Table contents, so manual edits are what gets exported."""
        from ..transcribe import Segment
        if not self.result:
            return []
        segs = []
        for row, seg in enumerate(self.result.segments):
            item = self.table.item(row, COL_TEXT)
            segs.append(Segment(seg.start, seg.end,
                                item.text() if item else seg.text,
                                suspicious=seg.suspicious))
        return segs

    # --------------------------------------------------------------- output
    def copy_text(self) -> None:
        from .. import export
        segs = self._current_segments()
        if not segs:
            return
        tr = self._current_translations()
        active = export._active_translations(tr)
        if active:
            QApplication.clipboard().setText(
                export.render_txt(export._as_cues(segs), False,
                                  export._variants(active, len(segs))))
        else:
            QApplication.clipboard().setText(render_txt(segs))
        self.statusBar().showMessage(t("status.copied"))

    def export(self) -> None:
        from .. import export
        segs = self._current_segments()
        if not segs:
            return
        base = self.video_path.stem if self.video_path else "transcript"
        start, end = self._current_range()
        stamp = f"{start.replace(':', '')}-{end.replace(':', '')}"
        path, _ = QFileDialog.getSaveFileName(
            self, t("filedialog.export"), f"{base}_{stamp}.xlsx",
            export.export_dialog_filters())
        if not path:
            return
        p = Path(path)
        fmt = export.guess_format(p.name)
        try:
            export.write(p, segs, fmt, lang=get_language(),
                         json_payload=self.result.to_dict() if self.result else {},
                         translations=self._current_translations())
        except (OSError, export.ExportError) as exc:
            QMessageBox.critical(self, t("dlg.export_failed"), str(exc))
            return
        self.statusBar().showMessage(t("status.exported", path=p))

    def export_clip(self) -> None:
        if not self.video_path or not self.result or not self.result.segments:
            return
        start = self.result.segments[0].start
        end = self.result.segments[-1].end
        path, _ = QFileDialog.getSaveFileName(
            self, t("filedialog.clip"),
            f"{self.video_path.stem}_clip.mp4", t("filter.mp4"))
        if not path:
            return
        try:
            media.clip(self.video_path, Path(path), start, end)
        except media.MediaError as exc:
            QMessageBox.critical(self, t("dlg.export_failed"), str(exc))
            return
        self.statusBar().showMessage(t("status.exported_clip", path=path))

    # ------------------------------------------------------------- drag/drop
    def dragEnterEvent(self, ev: QDragEnterEvent) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev: QDropEvent) -> None:
        for url in ev.mimeData().urls():
            if url.isLocalFile():
                self.load_video(Path(url.toLocalFile()))
                ev.acceptProposedAction()
                return

    def closeEvent(self, ev) -> None:
        self._close_load_dialog()
        if self.loader is not None:
            self.loader.cancel()
            # The worker kills its own ffmpeg, so this returns promptly; the
            # long wait only matters if the OS is wedged.
            if not self.loader.wait(10000):
                self.loader.setParent(None)   # do not destroy a live thread
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(5000)
        if self.tr_worker is not None:
            self.tr_worker.cancel()
            self.tr_worker.wait(5000)
        self.player.stop()
        super().closeEvent(ev)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    lang = None
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv):
            lang = argv[i + 1]
            break
        if a.startswith("--lang="):
            lang = a.split("=", 1)[1]
            break
    if lang:
        set_language(lang)

    app = QApplication.instance() or QApplication(argv[:1])
    app.setApplicationName("asr-mm")
    win = MainWindow()
    win.show()
    rest = [a for a in argv[1:] if a != "--lang" and a != lang]
    if rest and Path(rest[0]).exists():
        win.load_video(Path(rest[0]))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
