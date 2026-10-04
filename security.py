"""Security primitives: password hashing, tokens, secret vault encryption,
SSRF-safe outbound HTTP, rate limiting and filename hygiene."""
import base64
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
import threading
import time
import unicodedata
from collections import defaultdict, deque
from urllib.parse import urljoin, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken

import config

# ------------------------------------------------------------- passwords
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R,
                        p=_SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        dk = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt_b64),
                            n=int(n), r=int(r), p=int(p), dklen=len(expected),
                            maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


# Precomputed so that login with an unknown e-mail costs the same time.
DUMMY_HASH = hash_password(secrets.token_urlsafe(12))


def password_problem(password: str, email: str = "") -> str:
    if len(password) < 10:
        return "Password must be at least 10 characters."
    if len(password) > 256:
        return "Password is too long."
    if email and password.lower() == email.lower():
        return "Password must not be your e-mail address."
    if password.lower() in {"password123", "1234567890", "qwertyuiop", "inera12345"}:
        return "That password is too common."
    classes = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w]"))
    if classes < 2:
        return "Use a mix of letters, numbers or symbols."
    return ""


# ------------------------------------------------------------- tokens
def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hmac_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------- vault
def _fernet() -> Fernet:
    key = hashlib.sha256(("inera-vault:" + config.SECRET_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_json(obj: dict) -> str:
    return _fernet().encrypt(json.dumps(obj).encode("utf-8")).decode()


def decrypt_json(token: str) -> dict:
    try:
        return json.loads(_fernet().decrypt(token.encode()).decode("utf-8"))
    except (InvalidToken, ValueError):
        return {}


def mask(value: str) -> str:
    if not value:
        return ""
    value = str(value)
    if len(value) <= 6:
        return "•" * len(value)
    return value[:3] + "•" * min(12, len(value) - 6) + value[-3:]


# ------------------------------------------------------------- SSRF guard
class UnsafeURL(ValueError):
    pass


def _ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


def resolve_public(host: str, port: int = 0) -> str:
    """Resolve host, require every address to be public, and return one address to connect to.
    Connecting to this exact address (instead of resolving again) defeats DNS-rebinding tricks."""
    if not host:
        raise UnsafeURL("Missing host.")
    try:
        infos = socket.getaddrinfo(host, port or None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURL(f"Cannot resolve host '{host}'.") from exc
    ips = [info[4][0] for info in infos]
    if not config.ALLOW_PRIVATE_NETWORK:
        for ip in ips:
            if not _ip_is_public(ip):
                raise UnsafeURL(f"Blocked: '{host}' points to a private or reserved network address.")
    return ips[0]


def assert_public_host(host: str) -> None:
    """Raise UnsafeURL if host resolves to a private / loopback / reserved address."""
    if config.ALLOW_PRIVATE_NETWORK:
        return
    resolve_public(host)


def assert_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURL("Only http(s) URLs are allowed.")
    if parsed.username or parsed.password:
        raise UnsafeURL("URLs with embedded credentials are not allowed.")
    assert_public_host(parsed.hostname or "")
    return url


def _env_proxy() -> bool:
    import urllib.request
    proxies = urllib.request.getproxies()
    return bool(proxies.get("https") or proxies.get("http") or proxies.get("all"))


def _pinned(url: str):
    """Rewrite url to the vetted IP address; keep Host header and TLS name of the original host."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURL("Only http(s) URLs are allowed.")
    if parsed.username or parsed.password:
        raise UnsafeURL("URLs with embedded credentials are not allowed.")
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    ip = resolve_public(host, port)
    if _env_proxy() or config.ALLOW_PRIVATE_NETWORK:
        return url, {}, {}  # an operator-configured proxy performs the connection
    ip_host = f"[{ip}]" if ":" in ip else ip
    netloc = ip_host + (f":{parsed.port}" if parsed.port else "")
    host_header = host + (f":{parsed.port}" if parsed.port else "")
    ext = {"sni_hostname": host} if parsed.scheme == "https" else {}
    return parsed._replace(netloc=netloc).geturl(), {"Host": host_header}, ext


_HOP_HEADERS = {"content-encoding", "content-length", "transfer-encoding", "connection"}


def safe_request(method: str, url: str, *, max_bytes: int = 5 * 1024 * 1024,
                 timeout: float = 30, max_redirects: int = 3, deadline: float = 60, **kwargs) -> httpx.Response:
    """HTTP request to a user-supplied URL: SSRF checks and IP pinning on every redirect hop,
    an overall deadline and a hard cap on the response size."""
    base_headers = {"User-Agent": config.USER_AGENT}
    base_headers.update(kwargs.pop("headers", {}) or {})
    current = url
    started = time.monotonic()
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        for _ in range(max_redirects + 1):
            target, extra_headers, ext = _pinned(current)
            headers = {**base_headers, **extra_headers}
            with client.stream(method, target, headers=headers, extensions=ext, **kwargs) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    current = urljoin(current, resp.headers["location"])
                    if resp.status_code == 303:
                        method, kwargs = "GET", {}
                    continue
                chunks, total = [], 0
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise UnsafeURL(f"Response larger than {max_bytes // (1024 * 1024)} MB.")
                    if time.monotonic() - started > deadline:
                        raise UnsafeURL("The remote server is too slow.")
                    chunks.append(chunk)
                body = b"".join(chunks)
                clean = [(k, v) for k, v in resp.headers.multi_items() if k.lower() not in _HOP_HEADERS]
                return httpx.Response(resp.status_code, headers=clean, content=body,
                                      request=httpx.Request(method, current))
    raise UnsafeURL("Too many redirects.")


# ------------------------------------------------------------- SMTP with pinned address
def smtp_connect(host: str, port: int, mode: str, timeout: float = 40):
    """Open an SMTP connection to a vetted public address, verifying TLS against the real hostname."""
    import smtplib
    import ssl
    ip = resolve_public(host, port)
    context = ssl.create_default_context()
    if mode == "ssl":
        class _SSL(smtplib.SMTP_SSL):
            def _get_socket(self, h, p, t):
                sock = socket.create_connection((ip, p), t, self.source_address)
                return self.context.wrap_socket(sock, server_hostname=host)
        server = _SSL(timeout=timeout, context=context)
        server.connect(host, port)
    else:
        class _Plain(smtplib.SMTP):
            def _get_socket(self, h, p, t):
                return socket.create_connection((ip, p), t, self.source_address)
        server = _Plain(timeout=timeout)
        server.connect(host, port)
        server.ehlo()
        if mode == "starttls":
            server.starttls(context=context)
            server.ehlo()
    return server


# ------------------------------------------------------------- rate limit
class RateLimiter:
    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: float) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self._hits) > 50000:  # bound memory under attack
                for k in list(self._hits)[:10000]:
                    if not self._hits[k]:
                        del self._hits[k]
            return True


limiter = RateLimiter()


# ------------------------------------------------------------- filenames
def safe_filename(name: str, default: str = "file") -> str:
    name = unicodedata.normalize("NFKC", name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^\w.\- ()\[\]]+", "_", name, flags=re.UNICODE).strip(" ._")
    if not name:
        name = default
    if len(name) > 120:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:100] + "." + ext[:15]) if dot else name[:120]
    return name


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}$")


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email or ""))
