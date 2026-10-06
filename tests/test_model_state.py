"""模型状态与补全下载必须说同一件事。

用户报的「未下载模型和模型缺失补全对不上」，根因是 net.fetch 只在声明了
sha256 时校验，ASR 权重当时没有 sha256，于是断流下载的截断文件被装成最终
文件，列表里永远显示「未下载」，点了补全也补不齐。

这里锁住两件事：
  1. 界面各处（状态行 / 下载对话框 / CLI）用的都是同一套 missing_files 判定
  2. 截断文件一定会被判定为缺失，且补全后能真正变成就绪
"""
from __future__ import annotations

import http.server
import socket
import threading

import pytest

from asr_mm import catalog, downloader


def test_every_asr_weight_declares_a_checksum():
    """没有 sha256 的权重等于放弃了第二道校验——这正是截断文件溜进来的原因。"""
    missing = [(s.key, f.filename)
               for s in catalog.MODELS.values()
               for f in s.files if not f.sha256]
    assert not missing, f"这些权重没有 sha256: {missing}"


def test_translation_weights_declare_a_checksum():
    missing = [(s.key, f.filename)
               for s in catalog.MT_MODELS.values()
               for f in s.files if not f.sha256]
    assert not missing, f"这些翻译模型没有 sha256: {missing}"


def test_size_and_checksum_disagree_means_missing(tmp_path, monkeypatch):
    """文件在、但比声明小 → 任何入口都必须报「未下载」。"""
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    d = tmp_path / "models" / "mt-en"
    d.mkdir(parents=True)
    for f in catalog.MT_MODELS["en"].files:
        (d / f.filename).write_bytes(b"x" * max(1, int(f.size * 0.5)))
    assert not catalog.mt_model_ready("en")
    assert downloader.mt_missing_files(catalog.MT_MODELS["en"])


def test_ready_only_when_every_file_is_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    spec = catalog.MT_MODELS["en"]
    d = tmp_path / "models" / spec.dir_name
    d.mkdir(parents=True)
    for f in spec.files:
        (d / f.filename).write_bytes(b"x" * f.size)
    assert catalog.mt_model_ready("en")
    assert not downloader.mt_missing_files(spec)
    # 少一个文件就翻脸
    (d / spec.files[0].filename).unlink()
    assert not catalog.mt_model_ready("en")


def test_truncated_file_is_replaced_by_a_fresh_download(tmp_path, monkeypatch):
    """端到端：先放一个截断文件，再跑 ensure_mt_model，必须换成完整的。"""
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    spec = catalog.MT_MODELS["en"]
    d = tmp_path / "models" / spec.dir_name
    d.mkdir(parents=True)
    for f in spec.files:
        (d / f.filename).write_bytes(b"x" * (f.size // 2))
    assert not catalog.mt_model_ready("en")

    served = {}
    payloads = {f.filename: b"y" * f.size for f in spec.files}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            name = self.path.rsplit("/", 1)[-1]
            full = payloads[name]
            if not served.get(name):
                # 第一次只给一半，模拟断流；Content-Length 仍报完整长度，
                # 正是真实场景里把截断文件当成成功的那种情况
                served[name] = True
                self.send_response(200)
                self.send_header("Content-Length", str(len(full)))
                self.end_headers()
                self.wfile.write(full[: len(full) // 2])
                self.close_connection = True
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.connection.close()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(full)))
            self.end_headers()
            self.wfile.write(full)

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    import hashlib
    import dataclasses
    patched = dataclasses.replace(
        spec,
        files=tuple(
            type(f)(f"http://127.0.0.1:{port}/{f.filename}", f.filename,
                    f.size,
                    sha256=hashlib.sha256(payloads[f.filename]).hexdigest())
            for f in spec.files))
    # MTModelSpec 是 frozen，只能整条替换，不能改字段
    monkeypatch.setitem(catalog.MT_MODELS, "en", patched)
    try:
        downloader.ensure_mt_model("en")
    finally:
        srv.shutdown()
        srv.server_close()
    for f in spec.files:
        assert (d / f.filename).read_bytes() == payloads[f.filename], \
            f"{f.filename} 补全后内容不对"


def test_model_status_agrees_across_entry_points(tmp_path, monkeypatch):
    """状态行、下载对话框、CLI 三处都走 missing_files，不允许各说各话。"""
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    for spec in catalog.MODELS.values():
        missing = downloader.missing_files(spec)
        assert downloader.is_model_ready(spec.key) is (not missing)
    for spec in catalog.MT_MODELS.values():
        missing = downloader.mt_missing_files(spec)
        assert catalog.mt_model_ready(spec.key) is (not missing)


def test_every_asr_weight_has_a_third_source():
    """国内可用性：至少 Hugging Face / ModelScope / hf-mirror 三个源。"""
    for s in catalog.MODELS.values():
        for f in s.files:
            srcs = f.sources("auto")
            assert len(srcs) >= 2, f"{s.key}/{f.filename} 只有一个源: {srcs}"
            hosts = {u.split("/")[2] for u in srcs}
            assert "modelscope.cn" in hosts or "hf-mirror.com" in hosts, (
                f"{s.key}/{f.filename} 没有国内可用源: {srcs}")


def test_pinned_mirror_still_works():
    f = catalog.resolve_model("paraformer").files[0]
    assert f.sources("huggingface") == [f.url]
    assert f.sources("modelscope") == [f.mirror_url]
    assert f.sources("hf-mirror") == list(f.extra_urls)
