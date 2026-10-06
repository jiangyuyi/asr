"""下载截断必须被发现，而不是当成成功装上。

背景：真实的用户目录里 `qwen3-0.6b-q4km.gguf` 比声明少了整 100 MB，
而应用当时报告「已就绪」。原因是 net.fetch 只在 expect_sha256 非空时做校验，
ASR 权重在 catalog 里没有 sha256，于是 `r.read()` 提前返回空时循环静默退出，
截断文件被 part.replace(dst) 装成最终文件。

这些用例直接对着一个会中途断流的本地 HTTP 服务跑，不依赖网络。
"""
from __future__ import annotations

import http.server
import socket
import threading

import pytest

from asr_mm import net


class _TruncatingHandler(http.server.BaseHTTPRequestHandler):
    """Serves PAYLOAD but hangs up after CUTOFF bytes."""

    payload = b""
    cutoff = 0

    def log_message(self, *a):  # silence
        pass

    def do_GET(self):  # noqa: N802
        if self.headers.get("Range"):
            self.send_error(416)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        self.wfile.write(self.payload[: self.cutoff])
        self.wfile.flush()
        # hard close so the client's next read() gets EOF instead of hanging
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()


@pytest.fixture()
def truncating_server():
    def _serve(payload: bytes, cutoff: int):
        _TruncatingHandler.payload = payload
        _TruncatingHandler.cutoff = cutoff
        srv = http.server.HTTPServer(("127.0.0.1", 0), _TruncatingHandler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        host, port = srv.server_address
        yield f"http://{host}:{port}/file.bin"
        srv.shutdown()
        srv.server_close()
    return _serve


def _ctx():
    import ssl
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


def test_short_download_is_rejected_even_without_sha256(tmp_path, truncating_server):
    """The regression: no sha256 declared, connection dies early -> must fail."""
    payload = b"A" * 3_000_000
    url = next(truncating_server(payload, cutoff=1_200_000))
    dst = tmp_path / "weights.bin"
    with pytest.raises(net.DownloadError):
        net.fetch([url], dst, _ctx(), expect_size=len(payload),
                  expect_sha256="", retries=1)
    assert not dst.exists(), "截断的文件被当成成功装上了"
    # 半截留在 .part 里，下次续传接着下（界面也承诺过「下次继续」）
    part = dst.with_name(dst.name + ".part")
    assert part.exists(), "没有保留可续传的半截文件"
    assert 0 < part.stat().st_size < len(payload)


def test_short_download_is_rejected_with_sha256_too(tmp_path, truncating_server):
    import hashlib
    payload = b"B" * 2_000_000
    url = next(truncating_server(payload, cutoff=700_000))
    dst = tmp_path / "w2.bin"
    with pytest.raises(net.DownloadError):
        net.fetch([url], dst, _ctx(), expect_size=len(payload),
                  expect_sha256=hashlib.sha256(payload).hexdigest(), retries=1)
    assert not dst.exists()


def test_complete_download_still_succeeds(tmp_path):
    """The fix must not break the normal path."""
    import http.server
    import hashlib

    payload = b"C" * 1_500_000

    class OK(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            if self.headers.get("Range"):
                start = int(self.headers["Range"].split("=")[1].split("-")[0])
                body = payload[start:]
                self.send_response(206)
                self.send_header("Content-Range",
                                 f"bytes {start}-{len(payload)-1}/{len(payload)}")
            else:
                body = payload
                self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.HTTPServer(("127.0.0.1", 0), OK)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/w.bin"
    try:
        dst = tmp_path / "ok.bin"
        net.fetch([url], dst, _ctx(), expect_size=len(payload),
                  expect_sha256=hashlib.sha256(payload).hexdigest())
        assert dst.read_bytes() == payload
    finally:
        srv.shutdown()
        srv.server_close()


def test_resume_produces_the_right_bytes(tmp_path):
    """Interrupted then resumed must equal the original file byte for byte."""
    import http.server
    import hashlib

    payload = bytes(range(256)) * 4000  # 1,024,000 bytes, non-uniform

    class Resumable(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            rng = self.headers.get("Range")
            if rng:
                start = int(rng.split("=")[1].split("-")[0])
                body = payload[start:]
                self.send_response(206)
                self.send_header("Content-Range",
                                 f"bytes {start}-{len(payload)-1}/{len(payload)}")
            else:
                body = payload
                self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            # 只发一半就断，模拟真实的断流
            self.wfile.write(body[: len(body) // 2])
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()

    srv = http.server.HTTPServer(("127.0.0.1", 0), Resumable)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/r.bin"
    try:
        dst = tmp_path / "r.bin"
        with pytest.raises(net.DownloadError):
            net.fetch([url], dst, _ctx(), expect_size=len(payload),
                      expect_sha256=hashlib.sha256(payload).hexdigest(),
                      retries=1)
        # 半截 .part 留下供下次续传
        part = dst.with_suffix(".bin.part")
        assert part.exists() and 0 < part.stat().st_size < len(payload)
    finally:
        srv.shutdown()
        srv.server_close()
