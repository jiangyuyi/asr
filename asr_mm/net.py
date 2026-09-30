"""HTTPS that works from a frozen bundle, on a corporate network, and behind a
domestic mirror.

Three independent problems are handled here, because any one of them produces
the same opaque ``CERTIFICATE_VERIFY_FAILED`` to the user:

1. **No CA store at all.** A PyInstaller build does not carry the framework's
   ``etc/openssl/cert.pem``, so ``ssl.create_default_context()`` can end up with
   an empty trust store and reject *every* certificate. We always load an
   explicit bundle (``certifi``) on top of whatever the platform offers.

2. **Corporate TLS interception.** When a proxy re-signs traffic with its own
   root, that root lives in the OS keychain / cert store, not in any Python
   bundle. ``truststore`` teaches OpenSSL to read the OS store; without it the
   only fix is the user dropping the CA file in by hand.

3. **A single source being unreachable or slow.** Every model lists mirrors and
   the downloader walks them.

Security note: ``verify=False`` is available because some sites really are
behind an inspection proxy with no exportable CA, but it is opt-in, never the
default, and the UI states plainly that it removes authentication of the
download. Model weights are executable content; this is a real trade-off, not a
formality.
"""
from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

USER_AGENT = "asr-mm/1.3 (+https://github.com/jiangyuyi/asr)"

# Injection is global and must happen once, before any SSLContext is built.
_TRUSTSTORE_INJECTED = False
_CA_SOURCE = "unknown"


def inject_os_trust() -> str:
    """Teach OpenSSL to use the OS trust store. Returns what is now in use."""
    global _TRUSTSTORE_INJECTED, _CA_SOURCE
    try:
        import truststore  # noqa: F401
    except ImportError:
        _CA_SOURCE = "certifi (系统信任库不可用)"
        return _CA_SOURCE
    if not _TRUSTSTORE_INJECTED:
        try:
            truststore.inject_into_ssl()
            _TRUSTSTORE_INJECTED = True
            _CA_SOURCE = "系统信任库 + certifi"
        except Exception:  # noqa: BLE001 - truststore is best-effort
            _CA_SOURCE = "certifi（系统信任库注入失败）"
    return _CA_SOURCE


def ca_source() -> str:
    return _CA_SOURCE


@dataclass
class NetConfigLoaded:
    """Resolved network preferences, validated at load time."""
    ca_bundle: str = ""
    insecure: bool = False
    mirror: str = "auto"
    ca_exists: bool = False
    ca_error: str = ""

    @classmethod
    def load(cls, ca_bundle: str = "", insecure: bool = False,
             mirror: str = "auto") -> "NetConfigLoaded":
        bundle = (ca_bundle or "").strip()
        exists, error = True, ""
        if bundle:
            p = Path(bundle).expanduser()
            if not p.is_file():
                exists, error = False, f"找不到 CA 文件: {bundle}"
            elif p.stat().st_size < 200:
                exists, error = False, f"CA 文件太小，可能不是证书: {bundle}"
        return cls(ca_bundle=bundle, insecure=bool(insecure),
                   mirror=mirror or "auto", ca_exists=exists, ca_error=error)


class NetConfigError(RuntimeError):
    """The user's CA configuration is wrong — surfaced verbatim in the UI."""


def build_context(cfg: NetConfigLoaded | None = None) -> ssl.SSLContext:
    """An SSLContext that trusts as much as legitimately possible."""
    cfg = cfg or NetConfigLoaded()
    inject_os_trust()

    if cfg.insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    ctx = ssl.create_default_context()
    if not cfg.ca_exists and not cfg.ca_bundle:
        # Nothing configured: make sure we at least have the public roots.
        try:
            import certifi
            ctx.load_verify_locations(cafile=certifi.where())
        except Exception:  # noqa: BLE001
            pass
        return ctx

    if cfg.ca_bundle:
        if cfg.ca_exists:
            try:
                ctx.load_verify_locations(cafile=cfg.ca_bundle)
            except Exception as exc:  # noqa: BLE001
                raise NetConfigError(cfg.ca_error or f"CA 文件无法解析: {exc}")
        else:
            raise NetConfigError(cfg.ca_error)
    return ctx


class NetConfigError(RuntimeError):
    """The user's CA configuration is wrong — surfaced verbatim in the UI."""


class DownloadError(RuntimeError):
    """Every mirror failed. Carries the per-mirror reasons for the message."""

    def __init__(self, filename: str, attempts: list[tuple[str, str]]):
        self.filename = filename
        self.attempts = attempts
        detail = "; ".join(f"{host}: {why}" for host, why in attempts)
        super().__init__(f"{filename}\n{detail}")


def _classify(exc: Exception) -> tuple[str, bool, bool]:
    """(short reason, retry_same_mirror, try_next_mirror).

    These are different decisions. A 404 means the file is not on that host, so
    retrying it is pointless but another mirror may still have it. A timeout may
    be transient on the same host. Collapsing them into one flag made the
    downloader hammer a mirror that had already said "not here".
    """
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        if code == 404:
            return f"HTTP 404（该源没有这个文件）", False, True
        if code in (400, 410):
            return f"HTTP {code}", False, True
        if code == 403:
            return "HTTP 403（被拒绝，可能限流）", False, True
        return f"HTTP {code}", True, True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", exc)
        text = str(reason)
        if isinstance(reason, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in text:
            # Retrying the same host cannot help; a different host might not be
            # intercepted, so it is still worth one attempt.
            return "证书校验失败", False, True
        if "timed out" in text.lower():
            return "连接超时", True, True
        return text[:60], True, True
    return f"{type(exc).__name__}: {exc}"[:60], False, True


def host_of(url: str) -> str:
    return url.split("/")[2] if "//" in url else url


def open_url(url: str, ctx: ssl.SSLContext, offset: int = 0,
             timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if offset:
        req.add_header("Range", f"bytes={offset}-")
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def _try_mirror(url: str, part: Path, ctx: ssl.SSLContext, expect_size: int,
                expect_sha256: str, on_progress, timeout: int,
                retries: int) -> str:
    """Fetch one file from one mirror. Returns '' on success, else the reason.

    A transient failure (timeout, 5xx) is retried against the same host because
    the partial file is resumable. A definitive answer (404, certificate
    rejection) is not retried — asking again cannot change it.
    """
    host = host_of(url)
    reason = ""
    for attempt in range(1, retries + 1):
        offset = part.stat().st_size if part.exists() else 0
        try:
            _download_once(url, part, ctx, offset, expect_size,
                           on_progress, timeout)
            if expect_sha256:
                got = _sha256(part)
                if got != expect_sha256.lower():
                    part.unlink(missing_ok=True)
                    return "SHA256 不匹配"
            return ""
        except Exception as exc:  # noqa: BLE001
            reason, retry_same, try_next = _classify(exc)
            if retry_same and attempt < retries:
                continue
            if not try_next:
                # Nothing any other mirror can do either; stop early rather than
                # burn the user's time on a network that cannot work.
                raise _NoMirrorWillHelp(reason)
            break
    return reason


def fetch(urls: list[str], dst: Path, ctx: ssl.SSLContext, *,
          expect_size: int = 0, expect_sha256: str = "",
          on_progress=None, retries: int = 2, timeout: int = 60) -> Path:
    """Download ``dst``, walking ``urls`` in order until one succeeds.

    Resume is attempted per mirror; a mirror that ignores Range, or that fails
    permanently, leaves its partial file in place for the next one to continue.
    """
    if not urls:
        raise DownloadError(dst.name, [("-", "没有可用的下载源")])

    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_suffix(dst.suffix + ".part")
    attempts: list[tuple[str, str]] = []
    for url in urls:
        host = host_of(url)
        try:
            reason = _try_mirror(url, part, ctx, expect_size, expect_sha256,
                                 on_progress, timeout, retries)
        except _NoMirrorWillHelp as exc:
            attempts.append((host, exc.reason))
            break
        if not reason:
            part.replace(dst)
            return dst
        attempts.append((host, reason))
    raise DownloadError(dst.name, attempts)


class _NoMirrorWillHelp(RuntimeError):
    """A failure that no other mirror can fix; stop walking the list."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _download_once(url: str, part: Path, ctx: ssl.SSLContext, offset: int,
                   expect_size: int, on_progress, timeout: int) -> None:
    total = expect_size
    with open_url(url, ctx, offset=offset, timeout=timeout) as r:
        if offset and getattr(r, "status", 200) == 200:
            # Mirror ignored the Range header: start over.
            offset = 0
            part.unlink(missing_ok=True)
        length = int(r.headers.get("Content-Length") or 0)
        if length:
            total = length + offset
        done = offset
        if on_progress:
            on_progress(part.name, done, total)
        with part.open("ab" if offset else "wb") as f:
            while True:
                block = r.read(1 << 20)
                if not block:
                    break
                f.write(block)
                done += len(block)
                if on_progress:
                    on_progress(part.name, done, total)


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


# --------------------------------------------------------------------- diagnosis

PROBE_URLS = [
    ("Hugging Face", "https://huggingface.co/FunAudioLLM/fsmn-vad-GGUF/resolve/main/fsmn-vad.gguf"),
    ("ModelScope", "https://modelscope.cn/models/FunAudioLLM/fsmn-vad-GGUF/resolve/master/fsmn-vad.gguf"),
    ("GitHub", "https://github.com/"),
]


@dataclass
class ProbeResult:
    label: str
    host: str
    ok: bool
    reason: str = ""
    issuer: str = ""
    verdict: str = ""      # plain-language interpretation


def _peer_issuer(host: str, port: int = 443, timeout: int = 12) -> tuple[str, str]:
    """(issuer CN, subject CN) for a TLS peer, read *without* validating.

    Two wrinkles make this less trivial than it looks:

    * With ``CERT_NONE``, ``getpeercert()`` returns an empty dict, because Python
      only populates it for a chain it verified. So we take
      ``binary_form=True`` and decode the DER ourselves.
    * The decoder for that (``ssl._ssl._test_decode_cert``) is private. It has
      been stable for years, and this is a diagnostic, so we use it behind a
      guard and degrade to an empty issuer rather than failing.
    """
    import socket
    import tempfile

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    if not der:
        return "", ""
    pem = ssl.DER_cert_to_PEM_cert(der)
    tmp = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False,
                                      encoding="ascii")
    try:
        tmp.write(pem)
        tmp.close()
        decode = getattr(ssl, "_ssl", None)
        decode = getattr(decode, "_test_decode_cert", None) if decode else None
        if decode is None:
            return "", ""
        info = decode(tmp.name)
    except Exception:  # noqa: BLE001
        return "", ""
    finally:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except OSError:
            pass

    def first(entries) -> str:
        for rdn in entries or ():
            for k, v in rdn:
                if k == "commonName":
                    return v
        return ""

    return first(info.get("issuer")), first(info.get("subject"))


def diagnose(cfg: NetConfigLoaded | None = None) -> list[ProbeResult]:
    """Try each source and report what happened, in terms a user can act on."""
    cfg = cfg or NetConfigLoaded()
    results: list[ProbeResult] = []
    for label, url in PROBE_URLS:
        host = net_host(url)
        entry = ProbeResult(label=label, host=host, ok=False)
        try:
            ctx = build_context(cfg)
            req = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                entry.ok = getattr(r, "status", 200) < 400
        except Exception as exc:  # noqa: BLE001
            reason, _retry_same, _try_next = _classify(exc)
            entry.reason = reason
            entry.verdict = _verdict_for(reason)
        else:
            try:
                issuer, _subject = _peer_issuer(host)
                entry.issuer = issuer
            except Exception:  # noqa: BLE001
                entry.issuer = ""
            entry.verdict = _verdict_intercepted(entry.issuer)
        results.append(entry)
    return results


def net_host(url: str) -> str:
    return host_of(url)


def _verdict_for(reason: str) -> str:
    if "证书" in reason:
        return ("证书校验失败：如果浏览器能正常打开该网站，多半是公司网络的 TLS "
                "解密代理；请在「工具 → 网络设置」里指定公司根证书，"
                "或改用 ModelScope 镜像。")
    if "超时" in reason:
        return "连接超时：该源在当前网络不可达，可切换到 ModelScope 镜像。"
    if "403" in reason or "429" in reason:
        return "被拒绝（限流或需要认证）：稍后重试，或换源。"
    return f"失败：{reason}"


_INTERCEPT_MARKERS = (
    "zscaler", "palo alto", "fortinet", "f5", "netskope", "blue coat", "symantec",
    "citrix", "zscaler.com", "globalprotect", "sangfor", "firewall",
    "深信服", "sangfor", "barracuda", "mcafee", "webgateway", "zsapi",
)


def _verdict_intercepted(issuer: str) -> str:
    low = (issuer or "").lower()
    if not issuer:
        return "连接正常。"
    if any(marker in low for marker in _INTERCEPT_MARKERS):
        return (f"证书由 {issuer} 签发 —— 这是典型的企业 TLS 解密代理。"
                "浏览器信任它（系统钥匙串里有这张根证书），程序此前不信任。"
                "请在「工具 → 网络设置」里选择「使用系统信任库」，或指定该根证书文件。")
    return f"连接正常，证书由 {issuer} 签发。"
