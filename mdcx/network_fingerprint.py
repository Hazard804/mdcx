from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

RequestPurpose = Literal["document", "api", "asset", "download"]


@dataclass(frozen=True)
class BrowserFingerprint:
    """一组保持 TLS impersonate 与 HTTP 请求头一致的浏览器画像。"""

    fingerprint_id: str
    impersonate: str
    family: Literal["chrome", "firefox"]
    platform: str
    headers: dict[str, str]


_CHROME_136_WIN = BrowserFingerprint(
    fingerprint_id="chrome136_win",
    impersonate="chrome136",
    family="chrome",
    platform="Windows",
    headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
)

_CHROME_131_WIN = BrowserFingerprint(
    fingerprint_id="chrome131_win",
    impersonate="chrome131",
    family="chrome",
    platform="Windows",
    headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
)

_CHROME_124_WIN = BrowserFingerprint(
    fingerprint_id="chrome124_win",
    impersonate="chrome124",
    family="chrome",
    platform="Windows",
    headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
)

_CHROME_136_MAC = BrowserFingerprint(
    fingerprint_id="chrome136_macos",
    impersonate="chrome136",
    family="chrome",
    platform="macOS",
    headers={
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    },
)

_FIREFOX_133_WIN = BrowserFingerprint(
    fingerprint_id="firefox133_win",
    impersonate="firefox133",
    family="firefox",
    platform="Windows",
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
)

_FIREFOX_135_WIN = BrowserFingerprint(
    fingerprint_id="firefox135_win",
    impersonate="firefox135",
    family="firefox",
    platform="Windows",
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
)

_DEFAULT_FINGERPRINTS = (
    _CHROME_136_WIN,
    _CHROME_131_WIN,
    _CHROME_124_WIN,
    _CHROME_136_MAC,
    _FIREFOX_135_WIN,
    _FIREFOX_133_WIN,
)
_AMAZON_FINGERPRINTS = _DEFAULT_FINGERPRINTS

_ASSET_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
    ".avif",
    ".svg",
    ".ico",
    ".mp4",
    ".m4v",
    ".webm",
    ".m3u8",
    ".ts",
    ".zip",
    ".7z",
    ".rar",
)


def select_fingerprint(
    host: str,
    *,
    purpose: RequestPurpose = "document",
    exclude_fingerprint_id: str = "",
) -> BrowserFingerprint:
    normalized_host = (host or "").lower()
    if normalized_host.endswith("amazon.co.jp"):
        return select_amazon_fingerprint(exclude_fingerprint_id=exclude_fingerprint_id)
    if purpose == "api":
        return _choose_fingerprint((_CHROME_136_WIN, _CHROME_131_WIN), exclude_fingerprint_id=exclude_fingerprint_id)
    return _choose_fingerprint(_DEFAULT_FINGERPRINTS, exclude_fingerprint_id=exclude_fingerprint_id)


def select_amazon_fingerprint(*, exclude_fingerprint_id: str = "") -> BrowserFingerprint:
    return _choose_fingerprint(_AMAZON_FINGERPRINTS, exclude_fingerprint_id=exclude_fingerprint_id)


def _choose_fingerprint(
    fingerprints: tuple[BrowserFingerprint, ...],
    *,
    exclude_fingerprint_id: str = "",
) -> BrowserFingerprint:
    candidates = [each for each in fingerprints if each.fingerprint_id != exclude_fingerprint_id]
    return random.choice(candidates or list(fingerprints))


def infer_request_purpose(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    stream: bool = False,
    json_data: object | None = None,
) -> RequestPurpose:
    if stream:
        return "download"
    if _has_header(headers, "range"):
        return "download"
    if json_data is not None:
        return "api"
    accept = _get_header(headers, "accept").lower()
    content_type = _get_header(headers, "content-type").lower()
    if "application/json" in accept or "application/json" in content_type:
        return "api"
    if str(method).upper() == "HEAD":
        return "asset"

    try:
        path = urlsplit(url).path.lower()
    except Exception:
        path = ""
    if any(path.endswith(each_ext) for each_ext in _ASSET_EXTENSIONS):
        return "asset"
    return "document"


def should_apply_fingerprint(
    url: str,
    *,
    cf_bypass_url: str = "",
) -> bool:
    try:
        parsed = urlsplit(url)
    except Exception:
        return True

    host = (parsed.hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return False

    if cf_bypass_url:
        try:
            bypass_host = (urlsplit(cf_bypass_url).hostname or "").lower()
        except Exception:
            bypass_host = ""
        if bypass_host and host == bypass_host:
            return False
    return True


def build_fingerprint_headers(
    url: str,
    *,
    fingerprint: BrowserFingerprint,
    purpose: RequestPurpose = "document",
) -> dict[str, str]:
    headers = dict(fingerprint.headers)
    if purpose == "api":
        for key in ("Upgrade-Insecure-Requests", "Sec-Fetch-User"):
            _pop_case_insensitive(headers, key)
        headers["Accept"] = "application/json,text/plain,*/*"
        headers["Sec-Fetch-Dest"] = "empty"
        headers["Sec-Fetch-Mode"] = "cors"
        headers["Sec-Fetch-Site"] = "same-origin"
    elif purpose in {"asset", "download"}:
        for key in ("Upgrade-Insecure-Requests", "Sec-Fetch-User"):
            _pop_case_insensitive(headers, key)
        headers["Accept"] = "*/*"
        headers["Sec-Fetch-Dest"] = "empty"
        headers["Sec-Fetch-Mode"] = "no-cors"
        headers["Sec-Fetch-Site"] = "same-origin"

    try:
        host = (urlsplit(url).hostname or "").lower()
    except Exception:
        host = ""
    if host.endswith("amazon.co.jp"):
        headers["Accept-Language"] = "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"
    return headers


def build_amazon_headers(url: str, explicit_headers: dict[str, str] | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    headers["accept-language"] = "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"
    headers["Host"] = "www.amazon.co.jp"
    return merge_headers(None, headers, explicit_headers)


def merge_headers(
    fingerprint_headers: dict[str, str] | None,
    site_headers: dict[str, str] | None,
    explicit_headers: dict[str, str] | None,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for source in (fingerprint_headers or {}, site_headers or {}, explicit_headers or {}):
        for key, value in source.items():
            _set_case_insensitive(result, str(key), str(value))
    return result


def _get_header(headers: dict[str, str] | None, key: str) -> str:
    if not headers:
        return ""
    key_lower = key.lower()
    for each_key, value in headers.items():
        if str(each_key).lower() == key_lower:
            return str(value)
    return ""


def _has_header(headers: dict[str, str] | None, key: str) -> bool:
    return bool(_get_header(headers, key))


def _set_case_insensitive(headers: dict[str, str], key: str, value: str) -> None:
    key_lower = key.lower()
    for existing_key in list(headers):
        if existing_key.lower() == key_lower:
            headers.pop(existing_key, None)
    headers[key] = value


def _pop_case_insensitive(headers: dict[str, str], key: str) -> None:
    key_lower = key.lower()
    for existing_key in list(headers):
        if existing_key.lower() == key_lower:
            headers.pop(existing_key, None)
