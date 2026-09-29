"""PySide6 desktop UI: pick a time window on a video, transcribe it, edit, export."""
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
    QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QSplitter, QTableWidget,
    QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget,
)

from .. import __version__, catalog, downloader, engine, media, transcribe
from ..srt import format_ts, render_srt, render_txt
from .range_slider import RangeSlider
from .worker import Job, TranscribeWorker

VIDEO_FILTER = ("视频文件 (*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.m4v *.ts *.webm "
                "*.mpg *.mpeg *.rmvb *.3gp);;所有文件 (*.*)")
TEXT_FILTER = "文本文件 (*.txt);;字幕文件 (*.srt);;JSON (*.json)"


def tc(seconds: float) -> str:
    return format_ts(max(0.0, seconds), comma=False)


class DropVideoLabel(QLabel):
    """Click-to-browse tile shown until a video is loaded."""

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__("拖入视频文件\n或点击这里选择")
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setMinimumSize(480, 300)
        self.setStyleSheet(
            "border: 2px dashed #b9c0cc; border-radius: 10px;"
            "color:#6b7280; background:#fafbfc; font-size:15px;")

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
        self.setWindowTitle(f"asr-mm · 视频片段转写 {__version__}")
        self.resize(1180, 800)

        self.video_path: Path | None = None
        self.info: media.MediaInfo | None = None
        self.result: transcribe.Transcript | None = None
        self.worker: TranscribeWorker | None = None
        self.player_ok = False
        self._syncing = False
        self._pos_timer = QTimer(self)
        self._pos_timer.setInterval(200)
        self._pos_timer.timeout.connect(self._tick_playhead)

        self.settings = QSettings("asr-mm", "asr-mm")
        self._build_ui()
        self._build_menu()
        self._refresh_model_state()

    # ------------------------------------------------------------------- ui
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        # ---- top: open + model
        top = QHBoxLayout()
        self.btn_open = QPushButton("打开视频…")
        self.btn_open.clicked.connect(self.choose_video)
        self.lbl_file = QLabel("未选择文件")
        self.lbl_file.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_file.setStyleSheet("color:#6b7280;")
        top.addWidget(self.btn_open)
        top.addWidget(self.lbl_file, 1)
        top.addWidget(QLabel("模型"))
        self.cmb_model = QComboBox()
        for spec in catalog.MODELS.values():
            self.cmb_model.addItem(spec.label, spec.key)
        self.cmb_model.setCurrentIndex(0)
        self.cmb_model.currentIndexChanged.connect(lambda _: self._refresh_model_state())
        self.cmb_model.setToolTip("Nano 标点最完整；Paraformer 最快但无标点")
        top.addWidget(self.cmb_model)
        root.addLayout(top)

        # ---- middle splitter: preview | controls
        split = QSplitter(Qt.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.drop = DropVideoLabel()
        self.drop.clicked.connect(self.choose_video)
        ll.addWidget(self.drop)

        self.video = QVideoWidget()
        self.video.setMinimumSize(480, 300)
        self.video.setStyleSheet("background:#000; border-radius:8px;")
        self.video.hide()
        ll.addWidget(self.video)

        self.pos_slider = QWidget()  # placeholder keeps layout stable
        ll.addStretch(1)
        split.addWidget(left)

        right = QWidget()
        right.setMaximumWidth(340)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)

        rl.addWidget(self._section("时间区间"))
        self.slider = RangeSlider()
        self.slider.startMoved.connect(lambda v: self._set_time(self.spin_start, v))
        self.slider.endMoved.connect(lambda v: self._set_time(self.spin_end, v))
        self.slider.rangeChanged.connect(self._on_range_changed)
        rl.addWidget(self.slider)

        form = QFormLayout()
        self.spin_start = QTimeEdit()
        self.spin_end = QTimeEdit()
        for s in (self.spin_start, self.spin_end):
            s.setDisplayFormat("HH:mm:ss.zzz")
            s.setEnabled(False)
        self.spin_start.timeChanged.connect(self._on_spin_changed)
        self.spin_end.timeChanged.connect(self._on_spin_changed)

        b1 = QPushButton("起点 = 当前位置")
        b1.clicked.connect(lambda: self._set_range_from_player(0))
        b2 = QPushButton("终点 = 当前位置")
        b2.clicked.connect(lambda: self._set_range_from_player(1))
        for b in (b1, b2):
            b.setEnabled(False)
        self._range_buttons = (b1, b2)

        row = QHBoxLayout()
        row.addWidget(b1)
        row.addWidget(b2)
        form.addRow("开始", self.spin_start)
        form.addRow("结束", self.spin_end)
        form.addRow("", row)

        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_play.setEnabled(False)
        form.addRow("", self.btn_play)
        rl.addLayout(form)

        rl.addWidget(self._section("识别选项"))
        self.spin_preroll = QDoubleSpinBox()
        self.spin_preroll.setRange(0.0, 5.0)
        self.spin_preroll.setSingleStep(0.1)
        self.spin_preroll.setValue(0.0)
        self.spin_preroll.setSuffix(" 秒")
        self.spin_preroll.setToolTip("起点前多取一点，避免切到半个字")
        self.chk_drop = QCheckBox("过滤疑似噪音片段")
        self.chk_drop.setToolTip("丢掉极短且字数极少的识别结果（常见于纯噪音）")
        self.chk_loud = QCheckBox("先做响度归一化")
        f2 = QFormLayout()
        f2.addRow("预读", self.spin_preroll)
        f2.addRow("", self.chk_drop)
        f2.addRow("", self.chk_loud)
        rl.addLayout(f2)

        self.lbl_model_state = QLabel()
        self.lbl_model_state.setWordWrap(True)
        self.lbl_model_state.setStyleSheet("color:#6b7280; font-size:12px;")
        rl.addWidget(self.lbl_model_state)

        self.btn_run = QPushButton("开始转写")
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
        root.addWidget(self._section("识别结果"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["开始", "时长", "文字（可双击编辑）"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 80)
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
        self.btn_copy = QPushButton("复制全文")
        self.btn_copy.clicked.connect(self.copy_text)
        self.btn_save = QPushButton("导出…")
        self.btn_save.clicked.connect(self.export)
        self.btn_clip = QPushButton("导出该段视频")
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
        self.statusBar().showMessage("就绪。首次使用请先下载模型：asr-mm setup")

        self.player = QMediaPlayer(self)
        self.player.setVideoOutput(self.video)
        self.audio_out = QAudioOutput(self)
        self.audio_out.setVolume(1.0)
        self.player.setAudioOutput(self.audio_out)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.errorOccurred.connect(self._on_player_error)

    def _section(self, title: str) -> QLabel:
        lab = QLabel(title)
        lab.setStyleSheet("font-weight:600; color:#374151; padding-top:6px;")
        return lab

    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("文件(&F)")
        a = QAction("打开视频…", self)
        a.setShortcut(QKeySequence.Open)
        a.triggered.connect(self.choose_video)
        m.addAction(a)
        m.addSeparator()
        a2 = QAction("退出", self)
        a2.setShortcut(QKeySequence.Quit)
        a2.triggered.connect(self.close)
        m.addAction(a2)

        m2 = self.menuBar().addMenu("工具(&T)")
        a3 = QAction("下载缺失模型…", self)
        a3.triggered.connect(self.download_models)
        m2.addAction(a3)
        a4 = QAction("打开模型目录", self)
        a4.triggered.connect(self.open_models_dir)
        m2.addAction(a4)
        a5 = QAction("自检", self)
        a5.triggered.connect(self.doctor)
        m2.addAction(a5)

        h = self.menuBar().addMenu("帮助(&H)")
        a6 = QAction("关于", self)
        a6.triggered.connect(self.about)
        h.addAction(a6)

    # ----------------------------------------------------------------- video
    def choose_video(self) -> None:
        start = self.settings.value("last_dir", "")
        path, _ = QFileDialog.getOpenFileName(self, "选择视频", start, VIDEO_FILTER)
        if path:
            self.load_video(Path(path))

    def load_video(self, path: Path) -> None:
        try:
            info = media.probe(path)
        except media.MediaError as exc:
            QMessageBox.critical(self, "无法打开", str(exc))
            return
        self.video_path, self.info = path, info
        self.result = None
        self.table.setRowCount(0)
        for b in (self.btn_copy, self.btn_save, self.btn_clip):
            b.setEnabled(False)

        self.lbl_file.setText(f"{path.name}   ({tc(info.duration)} · "
                              f"{info.size_mb:.0f} MB · {info.audio_codec})")
        self.lbl_file.setToolTip(str(path))
        self.settings.setValue("last_dir", str(path.parent))

        self.slider.setDuration(info.duration)
        self.slider.setRange(0.0, info.duration)
        self._sync_spins(0.0, info.duration)
        for s in (self.spin_start, self.spin_end):
            s.setEnabled(True)
        for b in self._range_buttons:
            b.setEnabled(True)
        self.btn_run.setEnabled(True)

        self.drop.hide()
        self.video.show()
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        QTimer.singleShot(1200, lambda: self._confirm_playback(path))
        self.statusBar().showMessage(f"已加载 {path.name}，时长 {tc(info.duration)}")

    def _confirm_playback(self, path: Path) -> None:
        if self.video_path != path:
            return
        err = self.player.error()
        if err != QMediaPlayer.Error.NoError:
            self.player_ok = False
            self._show_poster(path)
            self.statusBar().showMessage(
                f"该格式无法在系统播放器中预览（{self.player.errorString()}）。"
                "不影响转写，可直接用时间输入框选择区间。")
            self.btn_play.setEnabled(False)
        else:
            self.player_ok = True
            self.btn_play.setEnabled(True)

    def _show_poster(self, path: Path) -> None:
        """Preview fallback: a single ffmpeg-extracted frame in the drop tile."""
        with tempfile.TemporaryDirectory() as td:
            jpg = media.thumbnail(path, Path(td) / "poster.jpg", at=1.0)
            if not jpg:
                return
            from PySide6.QtGui import QPixmap
            pix = QPixmap(str(jpg))
            if pix.isNull():
                return
            self.video.hide()
            self.drop.setText("")
            self.drop.setPixmap(pix.scaled(
                self.drop.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.drop.setStyleSheet("border-radius:10px; background:#000;")
            self.drop.show()

    def _toggle_play(self) -> None:
        if not self.player_ok:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_position(self, pos: int) -> None:
        self.slider.setPlayhead(pos / 1000.0)
        if not self._syncing:
            self.statusBar().showMessage(f"播放位置 {tc(pos / 1000.0)}")

    def _on_duration(self, dur: int) -> None:
        if dur > 0 and self.info and abs(self.info.duration - dur / 1000.0) > 0.5:
            pass  # trust the ffprobe value; Qt rounds container durations

    def _tick_playhead(self) -> None:
        if self.player_ok and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.statusBar().showMessage(f"播放位置 {tc(self.player.position() / 1000.0)}")

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
        t = spin.time()
        return t.hour() * 3600 + t.minute() * 60 + t.second() + t.msec() / 1000.0

    def _on_range_changed(self, start: float, end: float) -> None:
        if self._syncing:
            return
        self._sync_spins(start, end)

    def _set_range_from_player(self, which: int) -> None:
        pos = self.player.position() / 1000.0
        start, end = self.slider.range()
        if which == 0:
            self.slider.setRange(min(pos, end - 0.1), end)
        else:
            self.slider.setRange(start, max(pos, start + 0.1))
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
        if missing:
            names = "、".join(m.filename for m in missing[:2])
            self.lbl_model_state.setText(f"⚠ 模型未下载，缺少 {len(missing)} 个文件（{names}…）\n"
                                         "点菜单「工具 → 下载缺失模型」")
        else:
            self.lbl_model_state.setText(
                f"✓ {spec.key} 已就绪 · {downloader.human(sum(f.size for f in spec.files))}")
        if self.worker is None:
            self.btn_run.setEnabled(bool(self.video_path) and not missing)

    def download_models(self) -> None:
        from .model_dialog import ModelDownloadDialog
        dlg = ModelDownloadDialog(self)
        dlg.exec()
        self._refresh_model_state()

    def open_models_dir(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from .. import paths
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.models_dir())))

    def doctor(self) -> None:
        from .. import paths
        lines = [f"{k}: {v}" for k, v in paths.describe_layout().items()]
        rt = downloader.runtime_status()
        lines.insert(0, f"运行时: {'已就绪' if rt['ready'] else '未安装'}")
        QMessageBox.information(self, "环境自检", "\n".join(lines))

    def about(self) -> None:
        QMessageBox.about(
            self, "关于 asr-mm",
            f"<b>asr-mm {__version__}</b><br><br>"
            "视频指定时间段 → 中文语音转写<br>"
            "本地离线运行，模型来自 FunASR（MIT）。<br><br>"
            "<span style='color:#6b7280'>Ctrl+O 打开视频 · "
            "双击结果行可编辑文字 · 点击结果行跳转播放位置</span>")

    # ------------------------------------------------------------------ run
    def run_transcribe(self) -> None:
        if not self.video_path or self.worker is not None:
            return
        key = self.cmb_model.currentData()
        if not downloader.is_model_ready(key):
            QMessageBox.warning(self, "模型缺失",
                                f"模型 {key} 尚未下载完成。\n"
                                "请先执行「工具 → 下载缺失模型」。")
            return
        start, end = self._current_range()
        self.btn_run.setEnabled(False)
        self.progress.show()
        self.statusBar().showMessage("正在识别…")
        job = Job(video=str(self.video_path), start=start, end=end, model=key,
                  preroll=self.spin_preroll.value(),
                  drop_short=self.chk_drop.isChecked(),
                  loudnorm=self.chk_loud.isChecked(),
                  maxseg=engine.DEFAULT_MAXSEG_MS)
        self.worker = TranscribeWorker(job, self)
        self.worker.stage.connect(self.statusBar().showMessage)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_done(self, result: transcribe.Transcript) -> None:
        self.worker = None
        self.result = result
        self.progress.hide()
        self.btn_run.setEnabled(True)
        self._fill_table(result)
        for b in (self.btn_copy, self.btn_save, self.btn_clip):
            b.setEnabled(True)
        speed = f"{1 / result.rtf:.0f}× 实时" if result.rtf else "—"
        self.statusBar().showMessage(
            f"完成：{len(result.segments)} 条片段，耗时 {result.elapsed:.1f}s / "
            f"音频 {result.audio_seconds:.0f}s（{speed}）"
            + (f"　|　{result.warning}" if result.warning else ""))

    def _on_failed(self, msg: str) -> None:
        self.worker = None
        self.progress.hide()
        self.btn_run.setEnabled(True)
        self.statusBar().showMessage("识别失败")
        QMessageBox.critical(self, "识别失败", msg)

    def _fill_table(self, result: transcribe.Transcript) -> None:
        self.table.setRowCount(len(result.segments))
        for row, seg in enumerate(result.segments):
            t0 = QTableWidgetItem(tc(seg.start))
            t1 = QTableWidgetItem(f"{seg.duration:.1f}s")
            t2 = QTableWidgetItem(seg.text)
            t2.setToolTip("双击可编辑")
            if seg.suspicious:
                t2.setBackground(Qt.GlobalColor.yellow)
                t2.setToolTip("疑似噪音误识别（黄色底色），可双击编辑或删除整行")
            for col, item in ((0, t0), (1, t1), (2, t2)):
                item.setFlags(item.flags() & ~Qt.ItemIsEditable if col < 2
                              else item.flags())
                self.table.setItem(row, col, item)
        self.table.resizeRowsToContents()

    def _on_row_selected(self) -> None:
        if not self.result or not self.table.currentRow() >= 0:
            return
        row = self.table.currentRow()
        if row < len(self.result.segments) and self.player_ok:
            self.player.setPosition(int(self.result.segments[row].start * 1000))
            self.player.play()

    def _current_segments(self) -> list:
        """Table contents, so manual edits are what gets exported."""
        from ..transcribe import Segment
        if not self.result:
            return []
        segs = []
        for row, seg in enumerate(self.result.segments):
            item = self.table.item(row, 2)
            segs.append(Segment(seg.start, seg.end,
                                item.text() if item else seg.text,
                                suspicious=seg.suspicious))
        return segs

    # --------------------------------------------------------------- output
    def copy_text(self) -> None:
        segs = self._current_segments()
        if not segs:
            return
        QApplication.clipboard().setText(render_txt(segs))
        self.statusBar().showMessage("已复制全文到剪贴板")

    def export(self) -> None:
        segs = self._current_segments()
        if not segs:
            return
        base = self.video_path.stem if self.video_path else "transcript"
        start, end = self._current_range()
        stamp = f"{start.replace(':', '')}-{end.replace(':', '')}"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出", f"{base}_{stamp}.txt", TEXT_FILTER)
        if not path:
            return
        p = Path(path)
        try:
            if p.suffix.lower() == ".srt":
                p.write_text(render_srt(segs), encoding="utf-8")
            elif p.suffix.lower() == ".json":
                p.write_text(json.dumps(self.result.to_dict(), ensure_ascii=False,
                                        indent=2), encoding="utf-8")
            else:
                p.write_text(render_txt(segs), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self.statusBar().showMessage(f"已导出 {p}")

    def export_clip(self) -> None:
        if not self.video_path or not self.result:
            return
        start, end = self.result.segments[0].start, self.result.segments[-1].end
        if not self.result.segments:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出片段视频", f"{self.video_path.stem}_clip.mp4",
            "MP4 (*.mp4);;所有文件 (*.*)")
        if not path:
            return
        try:
            media.clip(self.video_path, Path(path), start, end)
        except media.MediaError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self.statusBar().showMessage(f"已导出片段 {path}")

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
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(3000)
        self.player.stop()
        super().closeEvent(ev)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("asr-mm")
    win = MainWindow()
    win.show()
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        win.load_video(Path(sys.argv[1]))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
