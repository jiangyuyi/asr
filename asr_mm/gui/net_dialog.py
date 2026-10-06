"""Dialog for the network settings: download source, root CA, diagnostics.

The diagnostic is the important part. A CERTIFICATE_VERIFY_FAILED from a frozen
build and one from a corporate TLS-inspecting proxy look identical on the
surface, but the fixes differ: the first is a packaging bug, the second needs
the organisation's root certificate. This window tells them apart by reporting
who actually issued the certificate.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QVBoxLayout,
)

from .. import downloader, net, paths, settings as settings_mod
from ..i18n import t

MIRRORS = [
    ("auto", "net.mirror_auto"),
    ("huggingface", "net.mirror_hf"),
    ("modelscope", "net.mirror_ms"),
    ("hf-mirror", "net.mirror_hfm"),
]


class NetworkSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("net.title"))
        self.resize(680, 560)
        self.settings = settings_mod.Settings.load()
        self._worker = None

        lay = QVBoxLayout(self)
        intro = QLabel(t("net.intro"))
        intro.setWordWrap(True)
        lay.addWidget(intro)

        form = QFormLayout()
        self.cmb_mirror = QComboBox()
        for value, key in MIRRORS:
            self.cmb_mirror.addItem(t(key), value)
        idx = [v for v, _ in MIRRORS].index(self.settings.mirror) \
            if self.settings.mirror in [v for v, _ in MIRRORS] else 0
        self.cmb_mirror.setCurrentIndex(idx)
        form.addRow(t("net.mirror"), self.cmb_mirror)

        ca_row = QHBoxLayout()
        self.ed_ca = QLineEdit(self.settings.ca_bundle)
        self.ed_ca.setPlaceholderText(t("net.ca_none"))
        btn_browse = QPushButton(t("net.ca_browse"))
        btn_browse.clicked.connect(self._browse)
        btn_clear = QPushButton(t("net.ca_clear"))
        btn_clear.clicked.connect(lambda: self.ed_ca.clear())
        ca_row.addWidget(self.ed_ca, 1)
        ca_row.addWidget(btn_browse)
        ca_row.addWidget(btn_clear)
        holder = QWidget()
        holder.setLayout(ca_row)
        form.addRow(t("net.ca_bundle"), holder)

        self.chk_insecure = QCheckBox(t("net.insecure"))
        self.chk_insecure.setToolTip(t("net.insecure_tip"))
        self.chk_insecure.setChecked(self.settings.insecure)
        form.addRow("", self.chk_insecure)
        lay.addLayout(form)

        self.lbl_trust = QLabel()
        self.lbl_trust.setStyleSheet("color:#6b7280;")
        lay.addWidget(self.lbl_trust)

        self.btn_test = QPushButton(t("net.test"))
        self.btn_test.clicked.connect(self._test)
        lay.addWidget(self.btn_test)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.hide()
        lay.addWidget(self.bar)

        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setStyleSheet(
            "font-family: Menlo, Consolas, monospace; font-size: 12px;")
        lay.addWidget(self.out, 1)

        row = QHBoxLayout()
        self.btn_save = QPushButton(t("net.save"))
        self.btn_save.clicked.connect(self._save)
        self.btn_cancel = QPushButton(t("net.cancel"))
        self.btn_cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_cancel)
        lay.addLayout(row)

        self._refresh_trust_label()
        self.ed_ca.textChanged.connect(lambda _: self._refresh_trust_label())
        self.out.append(t("net.settings_path",
                          path=paths.settings_path()))

    # ------------------------------------------------------------------ state
    def _refresh_trust_label(self) -> None:
        cfg = downloader.net_config({
            "ca_bundle": self.ed_ca.text().strip(),
            "insecure": self.chk_insecure.isChecked(),
            "mirror": self.cmb_mirror.currentData(),
        })
        text = t("net.trust", source=net.inject_os_trust())
        if cfg.ca_error:
            text += "\n" + t("net.ca_bad", error=cfg.ca_error)
        elif cfg.ca_bundle:
            text += "\n" + t("net.ca_ok", path=cfg.ca_bundle)
        self.lbl_trust.setText(text)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, t("net.ca_bundle"), "",
            "Certificates (*.pem *.crt *.cer *.der);;All files (*.*)")
        if path:
            self.ed_ca.setText(path)

    def _test(self) -> None:
        cfg = downloader.net_config({
            "ca_bundle": self.ed_ca.text().strip(),
            "insecure": self.chk_insecure.isChecked(),
            "mirror": self.cmb_mirror.currentData(),
        })
        if cfg.ca_error:
            QMessageBox.warning(self, t("net.title"), cfg.ca_error)
            return
        if self.chk_insecure.isChecked() and not self._confirm_insecure():
            return
        self.out.append(t("net.testing"))
        self.bar.show()
        self.btn_test.setEnabled(False)
        try:
            for r in net.diagnose(cfg):
                status = (t("net.status_ok", label=r.label) if r.ok
                          else t("net.status_fail", label=r.label, reason=r.reason))
                self.out.append(f"● {status}")
                self.out.append(f"    {t('net.host')}: {r.host}")
                if r.issuer:
                    self.out.append(f"    {t('net.issuer')}: {r.issuer}")
                if r.verdict:
                    self.out.append(f"    {t('net.verdict')}: {r.verdict}")
        finally:
            self.bar.hide()
            self.btn_test.setEnabled(True)

    def _confirm_insecure(self) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(t("net.title"))
        box.setIcon(QMessageBox.Warning)
        box.setText(t("net.insecure_warn"))
        box.setStandardButtons(QMessageBox.Cancel)
        box.addButton(t("net.test"), QMessageBox.AcceptRole)
        return box.exec() == QMessageBox.AcceptRole

    def _save(self) -> None:
        self.settings.mirror = self.cmb_mirror.currentData()
        self.settings.ca_bundle = self.ed_ca.text().strip()
        self.settings.insecure = self.chk_insecure.isChecked()
        self.settings.save()
        self.accept()
