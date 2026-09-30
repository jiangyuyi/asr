"""Unit tests for the network layer: mirrors, TLS trust, error classification."""
import os
import ssl
import sys
import urllib.error

os.environ.setdefault("ASR_MM_HOME", os.path.join(os.path.dirname(__file__), ".testhome"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from asr_mm import catalog, downloader, net, settings as settings_mod  # noqa: E402

LANGS = ["zh", "en", "ja"]


# ----------------------------------------------------------------- catalog

def test_every_model_file_has_a_mirror():
    for spec in catalog.MODELS.values():
        for f in spec.files:
            assert f.mirror_url, f"{spec.key}/{f.filename} has no mirror"
            assert "modelscope.cn" in f.mirror_url


def test_mirror_points_at_the_same_file():
    for spec in catalog.MODELS.values():
        for f in spec.files:
            assert f.mirror_url.rsplit("/", 1)[-1] == f.filename
            assert "/resolve/master/" in f.mirror_url


def test_source_order_auto_prefers_huggingface():
    f = catalog.resolve_model("paraformer").files[0]
    urls = f.sources("auto")
    assert "huggingface.co" in urls[0]
    assert "modelscope.cn" in urls[1]


def test_source_order_pinned():
    f = catalog.resolve_model("paraformer").files[0]
    assert f.sources("huggingface") == [f.url]
    assert f.sources("modelscope") == [f.mirror_url]


def test_source_order_auto_falls_back_when_no_mirror():
    from asr_mm.catalog import ModelFile
    lonely = ModelFile("https://example.com/a.gguf", "a.gguf", 1)
    assert lonely.sources("auto") == ["https://example.com/a.gguf"]
    assert lonely.sources("modelscope") == ["https://example.com/a.gguf"]


def test_vad_file_shared_across_models():
    specs = [catalog.resolve_model(k) for k in catalog.MODELS]
    for spec in specs:
        assert any(f.filename == "fsmn-vad.gguf" for f in spec.files)


# -------------------------------------------------------------- net config

def test_config_defaults():
    cfg = net.NetConfigLoaded.load()
    assert cfg.mirror == "auto"
    assert cfg.insecure is False
    assert cfg.ca_bundle == ""
    assert cfg.ca_error == ""


def test_config_rejects_missing_ca(tmp_path):
    cfg = net.NetConfigLoaded.load(ca_bundle=str(tmp_path / "nope.pem"))
    assert not cfg.ca_exists
    assert "CA" in cfg.ca_error


def test_config_rejects_tiny_ca(tmp_path):
    p = tmp_path / "tiny.pem"
    p.write_text("x", encoding="ascii")
    cfg = net.NetConfigLoaded.load(ca_bundle=str(p))
    assert not cfg.ca_exists
    assert "太小" in cfg.ca_error or "not a cert" in cfg.ca_error


def test_config_accepts_real_looking_ca(tmp_path):
    p = tmp_path / "ca.pem"
    p.write_text("# " + "x" * 500, encoding="ascii")
    cfg = net.NetConfigLoaded.load(ca_bundle=str(p))
    assert cfg.ca_exists
    assert cfg.ca_error == ""


def test_context_is_verifying_by_default():
    ctx = net.build_context(net.NetConfigLoaded.load())
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_context_insecure_only_when_asked():
    ctx = net.build_context(net.NetConfigLoaded.load(insecure=True))
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False


def test_context_rejects_bad_ca_path(tmp_path):
    cfg = net.NetConfigLoaded.load(ca_bundle=str(tmp_path / "missing.pem"))
    with pytest.raises(net.NetConfigError):
        net.build_context(cfg)


def test_context_uses_the_given_ca(tmp_path):
    import certifi
    dst = tmp_path / "ca.pem"
    dst.write_bytes(open(certifi.where(), "rb").read())
    ctx = net.build_context(net.NetConfigLoaded.load(ca_bundle=str(dst)))
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    # get_ca_certs() is not implemented once truststore hands OpenSSL an
    # external store, so assert the store is usable the way that matters.
    import socket
    with socket.create_connection(("huggingface.co", 443), timeout=20) as s:
        with ctx.wrap_socket(s, server_hostname="huggingface.co") as tls:
            assert tls.getpeercert() != {}


# ------------------------------------------------------------- settings

def test_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    s = settings_mod.Settings.load()
    assert s.mirror == "auto"
    s.mirror = "modelscope"
    s.ca_bundle = "/tmp/root.pem"
    s.insecure = True
    s.save()
    again = settings_mod.Settings.load()
    assert again.mirror == "modelscope"
    assert again.ca_bundle == "/tmp/root.pem"
    assert again.insecure is True


def test_settings_survives_corruption(tmp_path, monkeypatch):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    s = settings_mod.Settings.load()
    assert s.mirror == "auto"


def test_settings_keeps_unknown_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        '{"mirror":"modelscope","future_flag":7}', encoding="utf-8")
    s = settings_mod.Settings.load()
    assert s.mirror == "modelscope"
    assert s.extra.get("future_flag") == 7


def test_downloader_reads_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    st = settings_mod.Settings()
    st.mirror = "modelscope"
    st.save()
    cfg = downloader.net_config()
    assert cfg.mirror == "modelscope"


# -------------------------------------------------------- error reporting

def _urlerror(msg):
    return urllib.error.URLError(msg)


def test_classify_404_does_not_retry_the_same_mirror_but_uses_the_next():
    exc = urllib.error.HTTPError("u", 404, "Not Found", None, None)
    reason, retry_same, try_next = net._classify(exc)
    assert "404" in reason
    assert retry_same is False      # it is not there; asking again is pointless
    assert try_next is True         # another mirror may still have it


def test_classify_403_uses_the_next_mirror():
    exc = urllib.error.HTTPError("u", 403, "Forbidden", None, None)
    reason, retry_same, try_next = net._classify(exc)
    assert "403" in reason
    assert retry_same is False
    assert try_next is True


def test_classify_ssl_error_never_retries_the_same_host():
    reason, retry_same, try_next = net._classify(
        _urlerror(ssl.SSLError("CERTIFICATE_VERIFY_FAILED")))
    assert "证书" in reason
    assert retry_same is False
    assert try_next is True


def test_classify_timeout_retries_the_same_host():
    reason, retry_same, try_next = net._classify(_urlerror("timed out"))
    assert "超时" in reason
    assert retry_same is True
    assert try_next is True


def test_explain_ssl_error_points_at_network_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    from asr_mm.i18n import set_language
    for lang, needle in (("zh", "网络设置"), ("en", "Network settings"),
                         ("ja", "ネットワーク設定")):
        set_language(lang)
        msg = downloader.explain(net.DownloadError(
            "paraformer-q8.gguf", [("huggingface.co", "证书校验失败")]))
        assert "paraformer-q8.gguf" in msg
        assert needle in msg, f"{lang} missing guidance"


def test_explain_mirror_failure_suggests_switching(tmp_path, monkeypatch):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    from asr_mm.i18n import set_language
    set_language("en")
    msg = downloader.explain(net.DownloadError(
        "x.gguf", [("huggingface.co", "连接超时"), ("modelscope.cn", "连接超时")]))
    assert "ModelScope" in msg
    assert "huggingface.co" in msg and "modelscope.cn" in msg


def test_explain_passes_through_config_errors():
    assert downloader.explain(net.NetConfigError("bad ca")) == "bad ca"


# ------------------------------------------------------------ mirror walk

def test_fetch_retries_a_timeout_on_the_same_mirror_then_falls_back(
        tmp_path, monkeypatch):
    calls = []

    def fake_once(url, part, ctx, offset, expect_size, on_progress, timeout):
        calls.append(url)
        if "huggingface.co" in url:
            raise urllib.error.URLError("timed out")
        part.write_bytes(b"payload")

    monkeypatch.setattr(net, "_download_once", fake_once)
    out = net.fetch(["https://huggingface.co/a", "https://modelscope.cn/a"],
                    tmp_path / "a.gguf", ssl.create_default_context(), retries=2)
    assert out.read_bytes() == b"payload"
    # a timeout may be transient, so HF gets a second try before we move on
    assert calls.count("https://huggingface.co/a") == 2
    assert calls[-1] == "https://modelscope.cn/a"


def test_fetch_does_not_hammer_a_host_that_said_404(tmp_path, monkeypatch):
    calls = []

    def not_here(url, *a, **k):
        calls.append(url)
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(net, "_download_once", not_here)
    with pytest.raises(net.DownloadError):
        net.fetch(["https://a.example/x", "https://b.example/x"],
                  tmp_path / "x.gguf", ssl.create_default_context(), retries=3)
    assert len(calls) == 2          # one attempt each, no pointless retries


def test_fetch_reports_every_mirror_it_tried(tmp_path, monkeypatch):
    def always_fail(url, *a, **k):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(net, "_download_once", always_fail)
    with pytest.raises(net.DownloadError) as exc:
        net.fetch(["https://a.example/x", "https://b.example/x"],
                  tmp_path / "x.gguf", ssl.create_default_context(), retries=1)
    assert {h for h, _ in exc.value.attempts} == {"a.example", "b.example"}


def test_fetch_rejects_a_corrupt_mirror_without_retrying(tmp_path, monkeypatch):
    calls = []

    def corrupt(url, part, ctx, offset, expect_size, on_progress, timeout):
        calls.append(url)
        part.write_bytes(b"wrong")

    monkeypatch.setattr(net, "_download_once", corrupt)
    with pytest.raises(net.DownloadError) as exc:
        net.fetch(["https://a.example/x", "https://b.example/x"],
                  tmp_path / "x.gguf", ssl.create_default_context(),
                  expect_sha256="0" * 64, retries=3)
    assert len(calls) == 2          # each mirror tried exactly once
    assert "SHA256" in exc.value.attempts[0][1]


def test_fetch_keeps_the_partial_file_between_mirrors(tmp_path, monkeypatch):
    seen = []

    def partial_then_full(url, part, ctx, offset, expect_size, on_progress, timeout):
        seen.append((url, offset))
        if "a.example" in url:
            part.write_bytes(b"0123456789")
            raise urllib.error.URLError("timed out")
        with part.open("ab") as f:
            f.write(b"tail")

    monkeypatch.setattr(net, "_download_once", partial_then_full)
    out = net.fetch(["https://a.example/x", "https://b.example/x"],
                    tmp_path / "x.bin", ssl.create_default_context(), retries=1)
    assert out.read_bytes() == b"0123456789tail"
    assert seen[1][1] == 10         # resumed, not restarted


def test_fetch_leaves_no_part_file_on_success(tmp_path, monkeypatch):
    def ok(url, part, ctx, offset, expect_size, on_progress, timeout):
        part.write_bytes(b"done")

    monkeypatch.setattr(net, "_download_once", ok)
    out = net.fetch(["https://a.example/x"], tmp_path / "x.bin",
                    ssl.create_default_context())
    assert out.exists()
    assert not (tmp_path / "x.bin.part").exists()


# ------------------------------------------------------------- i18n keys

def test_network_keys_exist_in_all_languages():
    from asr_mm import i18n
    for lang in LANGS:
        assert not i18n.missing_keys(lang), (
            f"{lang} missing: {i18n.missing_keys(lang)}")
