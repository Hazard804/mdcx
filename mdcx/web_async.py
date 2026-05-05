import asyncio
import contextlib
import random
import re
import sys
import threading
import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import aiofiles
import httpx
from aiolimiter import AsyncLimiter
from curl_cffi import AsyncSession, Response
from curl_cffi.requests.exceptions import ConnectionError, RequestException, Timeout
from curl_cffi.requests.session import HttpMethod
from curl_cffi.requests.utils import not_set
from PIL import Image

from .utils import collapse_inline_script_splits


class AsyncWebLimiters:
    def __init__(self):
        self.limiters: dict[str, AsyncLimiter] = {
            "127.0.0.1": AsyncLimiter(300, 1),
            "localhost": AsyncLimiter(300, 1),
        }

    def get(self, key: str, rate: float = 8, period: float = 1) -> AsyncLimiter:
        """默认对所有域名启用 8 req/s 的速率限制"""
        return self.limiters.setdefault(key, AsyncLimiter(rate, period))

    def remove(self, key: str):
        if key in self.limiters:
            del self.limiters[key]


class HostConnectionPool:
    def __init__(
        self,
        *,
        key: str,
        session_factory: Callable[[], AsyncSession],
        log_fn: Callable[[str], None],
    ):
        self.key = key
        self._session_factory = session_factory
        self._log = log_fn
        self.session = self._session_factory()
        self._sessions: dict[int, AsyncSession] = {0: self.session}
        self._active_by_generation: dict[int, int] = {}
        self._retired_generations: set[int] = set()
        self._session_lock = asyncio.Lock()
        self._closed = False
        self._generation = 0
        self.last_used_at = time.monotonic()

    async def begin_request(self) -> tuple[AsyncSession, int]:
        sessions_to_close: list[AsyncSession] = []
        async with self._session_lock:
            if self._closed:
                raise RuntimeError("网络连接池已关闭")
            generation = self._generation
            self._active_by_generation[generation] = self._active_by_generation.get(generation, 0) + 1
            self.last_used_at = time.monotonic()
            session = self.session
        await self._close_sessions(sessions_to_close)
        return session, generation

    async def end_request(self, generation: int) -> None:
        sessions_to_close: list[AsyncSession] = []
        async with self._session_lock:
            current_count = self._active_by_generation.get(generation, 0)
            if current_count <= 1:
                self._active_by_generation.pop(generation, None)
                if generation in self._retired_generations:
                    self._retired_generations.remove(generation)
                    old_session = self._sessions.pop(generation, None)
                    if old_session is not None:
                        sessions_to_close.append(old_session)
            else:
                self._active_by_generation[generation] = current_count - 1
            self.last_used_at = time.monotonic()
        await self._close_sessions(sessions_to_close)

    async def is_idle(self) -> bool:
        async with self._session_lock:
            return not self._active_by_generation

    async def reset(self, reason: str) -> None:
        if self._closed:
            return
        sessions_to_close: list[AsyncSession] = []
        async with self._session_lock:
            if self._closed:
                return
            sessions_to_close = self._rotate_locked(reason)
        await self._close_sessions(sessions_to_close)

    def _rotate_locked(self, reason: str) -> list[AsyncSession]:
        old_generation = self._generation
        self.session = self._session_factory()
        self._generation += 1
        self._sessions[self._generation] = self.session
        self.last_used_at = time.monotonic()
        self._log(f"♻️ 网络连接池已重建: {self.key.split('|', 1)[0]}")
        old_session = self._sessions.get(old_generation)
        if old_session is None:
            return []
        if self._active_by_generation.get(old_generation, 0) > 0:
            self._retired_generations.add(old_generation)
            return []
        self._sessions.pop(old_generation, None)
        self._retired_generations.discard(old_generation)
        return [old_session]

    async def _close_sessions(self, sessions: list[AsyncSession]) -> None:
        for session in sessions:
            with contextlib.suppress(Exception):
                await session.close()

    async def _close_all_sessions(self) -> None:
        sessions = list(self._sessions.values())
        self._sessions.clear()
        self._active_by_generation.clear()
        self._retired_generations.clear()
        await self._close_sessions(sessions)

    async def close(self) -> None:
        if self._closed:
            return
        async with self._session_lock:
            if self._closed:
                return
            self._closed = True
            await self._close_all_sessions()


class HostPoolManager:
    def __init__(
        self,
        *,
        session_factory: Callable[[], AsyncSession],
        log_fn: Callable[[str], None],
        idle_ttl: float = 600.0,
    ):
        self._session_factory = session_factory
        self._log = log_fn
        self._idle_ttl = idle_ttl
        self._pools: dict[str, HostConnectionPool] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    @staticmethod
    def key_for_url(url: str, proxy: str | None = None) -> str:
        parsed = httpx.URL(url)
        scheme = (parsed.scheme or "https").lower()
        host = (parsed.host or "").lower()
        port = parsed.port
        default_port = 443 if scheme == "https" else 80
        port_part = "" if port is None or port == default_port else f":{port}"
        proxy_part = (proxy or "").strip()
        return f"{scheme}://{host}{port_part}|proxy={proxy_part}"

    async def get(self, key: str) -> HostConnectionPool:
        if self._closed:
            raise RuntimeError("网络连接池管理器已关闭")
        async with self._lock:
            if self._closed:
                raise RuntimeError("网络连接池管理器已关闭")
            await self._cleanup_idle_locked()
            pool = self._pools.get(key)
            if pool is None:
                pool = HostConnectionPool(key=key, session_factory=self._session_factory, log_fn=self._log)
                self._pools[key] = pool
            return pool

    async def reset(self, key: str, reason: str) -> None:
        async with self._lock:
            pool = self._pools.get(key)
        if pool is not None:
            await pool.reset(reason)

    async def reset_all(self, reason: str) -> None:
        async with self._lock:
            pools = list(self._pools.values())
        await asyncio.gather(*(pool.reset(reason) for pool in pools), return_exceptions=True)

    async def is_idle(self) -> bool:
        async with self._lock:
            pools = list(self._pools.values())
        results = await asyncio.gather(*(pool.is_idle() for pool in pools), return_exceptions=True)
        return all(result is True for result in results)

    async def close(self) -> None:
        if self._closed:
            return
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            pools = list(self._pools.values())
            self._pools.clear()
        await asyncio.gather(*(pool.close() for pool in pools), return_exceptions=True)

    async def _cleanup_idle_locked(self) -> None:
        now = time.monotonic()
        expired: list[str] = []
        for key, pool in self._pools.items():
            if now - pool.last_used_at <= self._idle_ttl:
                continue
            if await pool.is_idle():
                expired.append(key)
        for key in expired:
            pool = self._pools.pop(key, None)
            if pool is not None:
                await pool.close()


class AsyncWebClient:
    def __init__(
        self,
        *,
        proxy: str | None = None,
        retry: int = 3,
        timeout: float,
        cf_bypass_url: str = "",
        cf_bypass_proxy: str | None = None,
        log_fn: Callable[[str], None] | None = None,
        limiters: AsyncWebLimiters | None = None,
        loop=None,
    ):
        self.retry = retry
        self.proxy = proxy
        self.timeout = timeout
        self.loop = loop
        self.max_clients = 50
        self._session_kwargs = {
            "loop": loop,
            "max_clients": self.max_clients,
            "verify": False,
            "max_redirects": 20,
            "timeout": timeout,
        }
        self._closed = False
        self._close_requested = False
        self._lease_lock = threading.Lock()
        self._leases = 0

        self.log_fn = log_fn if log_fn is not None else lambda _: None
        self.limiters = limiters if limiters is not None else AsyncWebLimiters()
        self._pool_manager = HostPoolManager(session_factory=self._new_curl_session, log_fn=self._log)

        self.cf_bypass_url = cf_bypass_url.strip().rstrip("/")
        self.cf_bypass_proxy = (cf_bypass_proxy or "").strip()
        self._cf_bypass_enabled = bool(self.cf_bypass_url)
        self._cf_host_locks: dict[str, asyncio.Lock] = {}
        self._cf_force_refresh_locks: dict[str, asyncio.Lock] = {}
        self._cf_host_retry_semaphores: dict[str, asyncio.Semaphore] = {}
        self._cf_locks_guard = asyncio.Lock()
        self._cf_last_bypass_attempt_at: dict[str, float] = {}
        self._cf_host_challenge_hits: dict[str, int] = {}
        self._cf_bypass_min_interval = 2.0
        self._cf_bypass_timeout = 45.0
        self._cf_bypass_retries = 2
        self._cf_mirror_max_redirects = 8
        self._cf_request_bypass_rounds = 2
        self._cf_retry_max_concurrent_per_host = 4
        self._cf_retry_after_bypass_base_delay = 1.2
        self._cf_retry_after_bypass_jitter = 1.3
        self._retry_sleep_jitter = 0.4

    def _new_curl_session(self) -> AsyncSession:
        return AsyncSession(
            **self._session_kwargs,
            impersonate=random.choice(["chrome123", "chrome124", "chrome131", "chrome136", "firefox133", "firefox135"]),
        )

    def retain(self) -> None:
        """声明一个长生命周期使用方正在持有客户端，避免配置重载时提前关闭连接池。"""
        with self._lease_lock:
            if self._closed:
                raise RuntimeError("网络客户端已关闭")
            self._leases += 1

    async def release(self) -> None:
        """释放长生命周期使用方。若已请求关闭，则在空闲后关闭底层连接池。"""
        with self._lease_lock:
            if self._leases > 0:
                self._leases -= 1
        if self._close_requested:
            await self._close_if_idle()

    def _lease_count(self) -> int:
        with self._lease_lock:
            return self._leases

    def _request_timeout_seconds(self, timeout: float | httpx.Timeout | None) -> float | None:
        if timeout is None or timeout is not_set:
            return float(self.timeout) + 5.0
        if isinstance(timeout, (int, float)):
            return float(timeout) + 5.0
        return None

    async def _is_idle(self) -> bool:
        return self._lease_count() == 0 and await self._pool_manager.is_idle()

    async def _close_if_idle(self) -> bool:
        if not await self._is_idle():
            return False
        await self.close()
        return True

    async def close_when_idle(self, *, poll_interval: float = 0.2) -> None:
        """等待所有持有方与进行中的请求结束后关闭连接池。"""
        self._close_requested = True
        while not await self._is_idle():
            await asyncio.sleep(poll_interval)
        await self.close()

    async def close(self) -> None:
        """关闭底层连接池。关闭后的客户端不可继续使用。"""
        if self._closed:
            return
        self._close_requested = True
        self._closed = True
        await self._pool_manager.close()

    async def reset_connections(self, reason: str, *, pool_key: str | None = None) -> None:
        """重建底层连接池，用于代理/节点不稳定后丢弃可能失效的连接。"""
        if self._closed:
            return
        if pool_key is None:
            await self._pool_manager.reset_all(reason)
        else:
            await self._pool_manager.reset(pool_key, reason)

    async def _record_transport_failure(self, error_msg: str, *, pool_key: str) -> None:
        await self.reset_connections(error_msg, pool_key=pool_key)

    async def _record_transport_success(self, *, pool_key: str) -> None:
        return

    async def _curl_request(self, **kwargs) -> Response:
        url = str(kwargs.get("url") or "")
        proxy = kwargs.get("proxy")
        pool_key = HostPoolManager.key_for_url(url, str(proxy) if proxy else None)
        if self._closed or (self._close_requested and self._lease_count() == 0):
            raise RuntimeError("网络客户端已关闭")
        pool = await self._pool_manager.get(pool_key)
        session, generation = await pool.begin_request()
        release_now = True
        try:
            coro = session.request(**kwargs)
            timeout_seconds = self._request_timeout_seconds(kwargs.get("timeout"))
            if timeout_seconds is None:
                response = await coro
            else:
                response = await asyncio.wait_for(coro, timeout=timeout_seconds)
            if kwargs.get("stream"):
                release_now = False
                return self._attach_stream_release(response, pool=pool, generation=generation)
            return response
        finally:
            if release_now:
                await pool.end_request(generation)

    def _attach_stream_release(self, response: Response, *, pool: HostConnectionPool, generation: int) -> Response:
        if getattr(response, "_mdcx_release_attached", False):
            return response

        released = False
        original_close = getattr(response, "close", None)
        original_aclose = getattr(response, "aclose", None)

        async def release_once() -> None:
            nonlocal released
            if released:
                return
            released = True
            await pool.end_request(generation)

        def close_wrapper(*args, **kwargs):
            try:
                if original_close is not None:
                    return original_close(*args, **kwargs)
                return None
            finally:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(release_once())
                except RuntimeError:
                    if self.loop and not self.loop.is_closed():
                        asyncio.run_coroutine_threadsafe(release_once(), self.loop)

        async def aclose_wrapper(*args, **kwargs):
            try:
                if original_aclose is not None:
                    return await original_aclose(*args, **kwargs)
                if original_close is not None:
                    return original_close()
                return None
            finally:
                await release_once()

        try:
            response.close = close_wrapper  # type: ignore[method-assign]
            response.aclose = aclose_wrapper  # type: ignore[method-assign]
            response._mdcx_release_attached = True  # type: ignore[attr-defined]
        except Exception:
            pass
        return response

    async def _close_response(self, response: Response | None) -> None:
        if response is None:
            return
        if hasattr(response, "aclose"):
            with contextlib.suppress(Exception):
                await response.aclose()
            return
        with contextlib.suppress(Exception):
            response.close()

    def _log(self, message: str) -> None:
        try:
            self.log_fn(message)
            return
        except UnicodeEncodeError:
            pass
        except Exception:
            return

        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_message = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
        try:
            self.log_fn(safe_message)
        except Exception:
            pass

    def _prepare_headers(self, url: str | None = None, headers: dict[str, str] | None = None) -> dict[str, str]:
        """预处理请求头"""
        if not headers:
            headers = {}

        # 根据URL设置特定的Referer
        if url:
            if "getchu" in url:
                headers.update({"Referer": "http://www.getchu.com/top.html"})
            elif "xcity" in url:
                headers.update(
                    {"referer": "https://xcity.jp/result_published/?genre=%2Fresult_published%2F&q=2&sg=main&num=60"}
                )
            elif "javbus" in url:
                headers.update({"Referer": "https://www.javbus.com/"})
            elif "giga" in url and "cookie_set.php" not in url:
                headers.update({"Referer": "https://www.giga-web.jp/top.html"})

        return headers

    async def _get_cf_host_lock(self, host: str) -> asyncio.Lock:
        async with self._cf_locks_guard:
            return self._cf_host_locks.setdefault(host, asyncio.Lock())

    async def _get_cf_force_refresh_lock(self, host: str) -> asyncio.Lock:
        async with self._cf_locks_guard:
            return self._cf_force_refresh_locks.setdefault(host, asyncio.Lock())

    async def _get_cf_host_retry_semaphore(self, host: str) -> asyncio.Semaphore:
        async with self._cf_locks_guard:
            if host not in self._cf_host_retry_semaphores:
                self._cf_host_retry_semaphores[host] = asyncio.Semaphore(
                    max(int(self._cf_retry_max_concurrent_per_host), 1)
                )
            return self._cf_host_retry_semaphores[host]

    def _calc_retry_sleep_seconds(self, attempt: int, *, after_cf_bypass: bool = False) -> float:
        if after_cf_bypass:
            base_delay = max(float(self._cf_retry_after_bypass_base_delay), 0.0)
            jitter = random.uniform(0.0, max(float(self._cf_retry_after_bypass_jitter), 0.0))
            return base_delay + jitter

        base_delay = max(float(attempt * 3 + 2), 0.0)
        jitter = random.uniform(0.0, max(float(self._retry_sleep_jitter), 0.0))
        return base_delay + jitter

    def _merge_cookies(
        self,
        cookies: dict[str, str] | None,
        bypass_cookies: dict[str, str] | None = None,
    ) -> dict[str, str] | None:
        base = dict(cookies or {})
        if bypass_cookies:
            base.update(bypass_cookies)
        return base or None

    def _extract_header_case_insensitive(self, headers: dict[str, Any], key: str) -> str:
        key_lower = key.lower()
        for k, v in headers.items():
            if str(k).lower() == key_lower:
                return str(v)
        return ""

    def _set_header_case_insensitive(self, headers: dict[str, str], key: str, value: str) -> None:
        key_lower = key.lower()
        for k in list(headers):
            if str(k).lower() == key_lower:
                headers.pop(k, None)
        headers[key] = value

    def _pop_header_case_insensitive(self, headers: dict[str, str], key: str) -> str:
        key_lower = key.lower()
        for k in list(headers):
            if str(k).lower() == key_lower:
                return headers.pop(k, "")
        return ""

    def _build_cookie_header(self, cookies: dict[str, str] | None) -> str:
        if not cookies:
            return ""
        pairs = [f"{str(k)}={str(v)}" for k, v in cookies.items() if k]
        return "; ".join(pairs)

    def _parse_cookie_header(self, cookie_header: str) -> dict[str, str]:
        parsed: dict[str, str] = {}
        for item in (cookie_header or "").split(";"):
            part = item.strip()
            if not part or "=" not in part:
                continue
            name, value = part.split("=", 1)
            parsed[name.strip()] = value.strip()
        return parsed

    def _merge_url_params(self, url: str, params: dict[str, Any] | list[tuple[str, Any]] | None) -> str:
        if not params:
            return url

        split_result = urlsplit(url)
        existing_items = parse_qsl(split_result.query, keep_blank_values=True)
        new_items = list(httpx.QueryParams(params).multi_items())
        merged_query = urlencode(existing_items + new_items, doseq=True)
        return urlunsplit(
            (
                split_result.scheme,
                split_result.netloc,
                split_result.path,
                merged_query,
                split_result.fragment,
            )
        )

    def _build_mirror_url(self, target_url: str) -> str:
        split_result = urlsplit(target_url)
        raw_path = split_result.path or "/"
        path = re.sub(r"/{2,}", "/", raw_path)
        mirror_url = f"{self.cf_bypass_url}{path}"
        if split_result.query:
            mirror_url = f"{mirror_url}?{split_result.query}"
        return mirror_url

    def _is_dmm_image_url(self, url: str) -> bool:
        normalized = str(url or "").strip()
        if normalized.startswith("//"):
            normalized = "https:" + normalized
        try:
            split_result = urlsplit(normalized)
        except Exception:
            return False

        host = split_result.netloc.lower()
        path = split_result.path.lower()
        if not host or not (host.endswith("dmm.co.jp") or host.endswith("dmm.com")):
            return False
        return path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"))

    def _is_redirect_response(self, response: Response) -> bool:
        if response.status_code not in (301, 302, 303, 307, 308):
            return False
        headers = {str(k): str(v) for k, v in response.headers.items()}
        return bool(self._extract_header_case_insensitive(headers, "location").strip())

    def _is_retryable_status_code(self, status_code: int) -> bool:
        return status_code in (
            500,  # Internal Server Error
            502,  # Bad Gateway
            503,  # Service Unavailable
            403,  # Forbidden
            408,  # Request Timeout
            429,  # Too Many Requests
            504,  # Gateway Timeout
        )

    def _extract_http_status_from_bypass_error(self, error: str, *, prefix: str) -> int | None:
        if not error:
            return None
        matched = re.match(rf"^{re.escape(prefix)}\s+(\d{{3}})\b", error.strip())
        if not matched:
            return None
        try:
            return int(matched.group(1))
        except Exception:
            return None

    def _extract_terminal_bypass_status(self, error: str) -> int | None:
        if not error:
            return None

        terminal_match = re.search(r"终态 HTTP (\d{3})", error)
        if terminal_match:
            try:
                return int(terminal_match.group(1))
            except Exception:
                return None

        mirror_status = self._extract_http_status_from_bypass_error(error, prefix="mirror HTTP")
        if mirror_status is not None:
            return mirror_status

        return self._extract_http_status_from_bypass_error(error, prefix="HTTP")

    def _is_mirror_cf_challenge_error(self, error: str) -> bool:
        if not error:
            return False
        normalized = error.strip()
        return normalized.startswith("mirror 返回 Cloudflare 挑战页") or "Cloudflare 挑战页" in normalized

    def _bind_response_effective_url(self, response: Response, final_url: str) -> None:
        normalized = (final_url or "").strip()
        if not normalized:
            return
        try:
            response.url = normalized
        except Exception:
            pass
        try:
            response.headers["x-mdcx-final-url"] = normalized
        except Exception:
            pass

    def _resolve_cf_bypass_proxy(self, *, use_proxy: bool) -> str:
        if not use_proxy:
            return ""
        return (self.cf_bypass_proxy or "").strip()

    def _prepare_mirror_headers(
        self,
        *,
        headers: dict[str, str] | None,
        target_host: str,
        cookies: dict[str, str] | None,
        use_proxy: bool,
        bypass_cache: bool = False,
    ) -> dict[str, str]:
        mirror_headers = dict(headers or {})
        self._pop_header_case_insensitive(mirror_headers, "host")
        self._set_header_case_insensitive(mirror_headers, "x-hostname", target_host)
        self._pop_header_case_insensitive(mirror_headers, "x-proxy")
        self._pop_header_case_insensitive(mirror_headers, "x-bypass-cache")
        bypass_proxy = self._resolve_cf_bypass_proxy(use_proxy=use_proxy)
        if bypass_proxy:
            self._set_header_case_insensitive(mirror_headers, "x-proxy", bypass_proxy)
        if bypass_cache:
            self._set_header_case_insensitive(mirror_headers, "x-bypass-cache", "true")

        header_cookie_map = self._parse_cookie_header(self._extract_header_case_insensitive(mirror_headers, "cookie"))
        merged_cookie_map = dict(cookies or {})
        merged_cookie_map.update(header_cookie_map)
        merged_cookie_header = self._build_cookie_header(merged_cookie_map)
        if merged_cookie_header:
            self._set_header_case_insensitive(mirror_headers, "Cookie", merged_cookie_header)
        elif header_cookie_map:
            self._set_header_case_insensitive(mirror_headers, "Cookie", self._build_cookie_header(header_cookie_map))
        else:
            self._pop_header_case_insensitive(mirror_headers, "cookie")

        return mirror_headers

    def _sanitize_url(self, url: str) -> tuple[str, bool]:
        cleaned = (url or "").strip()
        if not cleaned:
            return cleaned, False
        candidates: list[str] = []
        collapsed = collapse_inline_script_splits(cleaned).strip()
        if collapsed:
            candidates.append(collapsed)
        if cleaned not in candidates:
            candidates.append(cleaned)

        # 过滤类似 https://x.com?a=1">https://x.com?a=1 这类污染字符串，也兼容 Next.js 流式脚本分片插入。
        # 允许保留空格，随后交给 URL 解析器做编码，避免查询参数在空格处被截断。
        for source in candidates:
            source_matches: list[str] = []
            if match := re.match(r"^(https?://[^\"'<>]+)", source):
                source_matches.append(match.group(1).strip())
            if not source_matches:
                source_matches.extend(match.group(0).strip() for match in re.finditer(r"https?://[^\s\"'<>]+", source))

            for normalized in source_matches:
                try:
                    parsed = httpx.URL(normalized)
                except Exception:
                    continue
                if not parsed.host:
                    continue
                normalized = str(parsed)
                return normalized, normalized != cleaned

        return cleaned, False

    def _log_cf(self, message: str, host: str = "") -> None:
        host_prefix = f"{host} " if host else ""
        self._log(f"🛡️ [CF] {host_prefix}{message}")

    def _is_cf_challenge_response(self, response: Response) -> bool:
        status = response.status_code
        headers = {str(k): v for k, v in response.headers.items()}
        server = self._extract_header_case_insensitive(headers, "server").lower()
        cf_ray = self._extract_header_case_insensitive(headers, "cf-ray")

        content_type = self._extract_header_case_insensitive(headers, "content-type").lower()
        body_text = ""
        if "text/html" in content_type or not content_type:
            try:
                body_text = response.content[:8192].decode("utf-8", errors="ignore").lower()
            except Exception:
                body_text = ""

        challenge_markers = (
            "just a moment",
            "cf-chl",
            "cdn-cgi/challenge-platform",
            "attention required",
            "enable javascript and cookies",
            "checking your browser before accessing",
        )
        has_marker = any(marker in body_text for marker in challenge_markers)

        # 规则1: 明确 header + 挑战文案
        if status in (403, 429, 503) and ("cloudflare" in server or bool(cf_ray)) and has_marker:
            return True
        # 规则2: 挑战文案足够明确时，允许无 header 命中
        if has_marker and ("cf-chl" in body_text or "cdn-cgi/challenge-platform" in body_text):
            return True
        return False

    async def _call_bypass_mirror(
        self,
        *,
        method: HttpMethod,
        target_url: str,
        headers: dict[str, str] | None,
        cookies: dict[str, str] | None,
        use_proxy: bool,
        bypass_cache: bool = False,
        data: dict[str, str] | list[tuple] | str | BytesIO | bytes | None = None,
        json_data: dict[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        allow_redirects: bool = True,
    ) -> tuple[Response | None, str]:
        if not self._cf_bypass_enabled:
            return None, "未配置 bypass 地址"

        current_url = target_url
        current_method = str(method).upper()
        current_data = data
        current_json_data = json_data

        for redirect_index in range(self._cf_mirror_max_redirects + 1):
            try:
                target = httpx.URL(current_url)
                target_host = target.host or ""
            except Exception as exc:
                return None, f"mirror 目标 URL 解析失败: {exc}"

            if not target_host:
                return None, "mirror 目标 URL 缺少 host"

            if redirect_index == 0 and self._resolve_cf_bypass_proxy(use_proxy=use_proxy):
                self._log_cf("🌐 mirror bypass 将使用独立代理", target_host)
            if redirect_index == 0 and bypass_cache:
                self._log_cf("♻️ mirror bypass 将强制刷新 cookies", target_host)

            mirror_url = self._build_mirror_url(current_url)
            mirror_headers = self._prepare_mirror_headers(
                headers=headers,
                target_host=target_host,
                cookies=cookies,
                use_proxy=use_proxy,
                bypass_cache=bypass_cache,
            )
            mirror_pool_key = HostPoolManager.key_for_url(mirror_url, None)
            try:
                limiter = self.limiters.get("127.0.0.1")
                await limiter.acquire()
                response = await self._curl_request(
                    method=current_method,
                    url=mirror_url,
                    proxy=None,
                    headers=mirror_headers,
                    data=current_data,
                    json=current_json_data,
                    timeout=timeout or self._cf_bypass_timeout,
                    stream=False,
                    allow_redirects=False,
                )
                error = ""
            except Timeout:
                response = None
                error = "mirror 请求超时"
                await self._record_transport_failure(error, pool_key=mirror_pool_key)
            except ConnectionError as exc:
                response = None
                error = f"mirror 连接错误: {exc}"
                await self._record_transport_failure(error, pool_key=mirror_pool_key)
            except RequestException as exc:
                response = None
                error = f"mirror 请求异常: {exc}"
                await self._record_transport_failure(error, pool_key=mirror_pool_key)
            except TimeoutError:
                response = None
                error = "mirror 请求等待超时"
                await self._record_transport_failure(error, pool_key=mirror_pool_key)
            except Exception as exc:
                response = None
                error = f"mirror 未知错误: {exc}"
                await self._record_transport_failure(error, pool_key=mirror_pool_key)
            if response is None:
                return None, error

            self._bind_response_effective_url(response, current_url)
            response.headers["x-mdcx-bypass-mode"] = "mirror"

            if self._is_cf_challenge_response(response):
                return None, "mirror 返回 Cloudflare 挑战页"

            if response.status_code >= 400:
                return None, f"mirror HTTP {response.status_code}"

            if not allow_redirects or not self._is_redirect_response(response):
                return response, ""

            response_headers = {str(k): str(v) for k, v in response.headers.items()}
            location = self._extract_header_case_insensitive(response_headers, "location").strip()
            if not location:
                return response, ""

            next_url = urljoin(current_url, location)
            if not next_url:
                return None, "mirror 重定向 Location 为空"
            self._log_cf(f"➡️ mirror 跟随重定向: {current_url} -> {next_url}", target_host)

            if current_method not in ("GET", "HEAD") and response.status_code in (301, 302, 303):
                current_method = "GET"
                current_data = None
                current_json_data = None

            current_url = next_url
            if redirect_index >= self._cf_mirror_max_redirects:
                break

        return None, f"mirror 重定向超过上限 ({self._cf_mirror_max_redirects})"

    async def _call_bypass_html(
        self,
        target_url: str,
        *,
        use_proxy: bool,
        bypass_cache: bool = False,
    ) -> tuple[Response | None, str]:
        if not self._cf_bypass_enabled:
            return None, "未配置 bypass 地址"

        params: dict[str, Any] = {"url": target_url}
        bypass_proxy = self._resolve_cf_bypass_proxy(use_proxy=use_proxy)
        if bypass_proxy:
            params["proxy"] = bypass_proxy
            self._log_cf("🌐 /html bypass 将使用独立代理")
        if bypass_cache:
            params["bypassCookieCache"] = "true"
            self._log_cf("♻️ /html bypass 将强制刷新 cookies")

        response, error = await self.request(
            "GET",
            f"{self.cf_bypass_url}/html",
            use_proxy=False,
            allow_redirects=True,
            timeout=self._cf_bypass_timeout,
            params=params,
            enable_cf_bypass=False,
        )

        if response is None:
            return None, error

        if response.status_code >= 400:
            return None, f"HTTP {response.status_code}"

        if not response.content:
            return None, "bypass 返回空 HTML"

        response_headers = {str(k): str(v) for k, v in response.headers.items()}
        final_url = (
            self._extract_header_case_insensitive(response_headers, "x-cf-bypasser-final-url").strip() or target_url
        )
        self._bind_response_effective_url(response, final_url)
        response.headers["x-mdcx-bypass-mode"] = "html"
        return response, ""

    async def _try_bypass_cloudflare(
        self,
        *,
        host: str,
        method: HttpMethod,
        target_url: str,
        headers: dict[str, str] | None,
        cookies: dict[str, str] | None,
        data: dict[str, str] | list[tuple] | str | BytesIO | bytes | None,
        json_data: dict[str, Any] | None,
        timeout: float | httpx.Timeout | None,
        allow_redirects: bool,
        use_proxy: bool,
    ) -> tuple[Response | None, str]:
        lock = await self._get_cf_host_lock(host)
        async with lock:
            while True:
                now = time.monotonic()
                last_attempt = self._cf_last_bypass_attempt_at.get(host, 0.0)
                if last_attempt <= 0:
                    break

                elapsed = now - last_attempt
                if elapsed >= self._cf_bypass_min_interval:
                    break

                wait_seconds = self._cf_bypass_min_interval - elapsed
                if wait_seconds >= 0.2:
                    self._log_cf(f"🕒 bypass 冷却中 {wait_seconds:.2f}s，等待后继续", host)
                await asyncio.sleep(wait_seconds)

            self._cf_last_bypass_attempt_at[host] = time.monotonic()
            error = ""
            for i in range(self._cf_bypass_retries):
                if i == 0:
                    self._log_cf(f"🔐 尝试 mirror bypass: {target_url}", host)
                else:
                    self._log_cf(f"🔁 mirror bypass 重试 ({i + 1}/{self._cf_bypass_retries})", host)
                force_bypass_cache = i > 0

                can_retry = True
                html_bypass_cache = force_bypass_cache
                bypass_response, mirror_error = await self._call_bypass_mirror(
                    method=method,
                    target_url=target_url,
                    headers=headers,
                    cookies=cookies,
                    use_proxy=use_proxy,
                    bypass_cache=force_bypass_cache,
                    data=data,
                    json_data=json_data,
                    timeout=timeout,
                    allow_redirects=allow_redirects,
                )
                if bypass_response is not None:
                    self._cf_host_challenge_hits[host] = 0
                    return bypass_response, ""

                if self._is_mirror_cf_challenge_error(mirror_error) and not force_bypass_cache:
                    refresh_lock = await self._get_cf_force_refresh_lock(host)
                    async with refresh_lock:
                        self._log_cf("♻️ mirror 命中挑战页，判定缓存可能失效，强制刷新后重试 mirror", host)
                        bypass_response, mirror_error = await self._call_bypass_mirror(
                            method=method,
                            target_url=target_url,
                            headers=headers,
                            cookies=cookies,
                            use_proxy=use_proxy,
                            bypass_cache=True,
                            data=data,
                            json_data=json_data,
                            timeout=timeout,
                            allow_redirects=allow_redirects,
                        )
                    if bypass_response is not None:
                        self._cf_host_challenge_hits[host] = 0
                        return bypass_response, ""
                    html_bypass_cache = False

                mirror_status = self._extract_http_status_from_bypass_error(mirror_error, prefix="mirror HTTP")
                skip_html_fallback = mirror_status is not None and not self._is_retryable_status_code(mirror_status)
                if skip_html_fallback:
                    error = f"mirror 返回终态 HTTP {mirror_status}，跳过 /html 回退"
                    can_retry = False
                    self._log_cf(f"⚠️ {error}", host)
                elif str(method).upper() == "GET":
                    if html_bypass_cache:
                        self._log_cf(f"↩️ mirror 失败（强刷已启用），回退 /html: {mirror_error}", host)
                    else:
                        self._log_cf(f"↩️ mirror 失败，回退 /html: {mirror_error}", host)
                    bypass_response, html_error = await self._call_bypass_html(
                        target_url, use_proxy=use_proxy, bypass_cache=html_bypass_cache
                    )
                    if bypass_response is not None:
                        self._cf_host_challenge_hits[host] = 0
                        bypass_headers = {str(k): str(v) for k, v in bypass_response.headers.items()}
                        final_url = self._extract_header_case_insensitive(bypass_headers, "x-cf-bypasser-final-url")
                        if final_url and final_url.strip() and final_url.strip() != target_url:
                            self._log_cf(f"🌐 /html 最终地址: {final_url}", host)
                        return bypass_response, ""
                    error = f"mirror: {mirror_error}; html: {html_error}"
                else:
                    error = f"mirror 失败且 {str(method).upper()} 不支持 /html 兜底: {mirror_error}"
                    if mirror_status is not None and not self._is_retryable_status_code(mirror_status):
                        can_retry = False

                if not can_retry:
                    break

                if i < self._cf_bypass_retries - 1:
                    sleep_seconds = self._calc_retry_sleep_seconds(i, after_cf_bypass=True)
                    self._log_cf(f"⚠️ bypass 获取失败，{sleep_seconds:.2f}s 后重试: {error}", host)
                    await asyncio.sleep(sleep_seconds)

            return None, error or "bypass HTML 获取失败"

    async def request(
        self,
        method: HttpMethod,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
        use_proxy: bool = True,
        data: dict[str, str] | list[tuple] | str | BytesIO | bytes | None = None,
        json_data: dict[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        stream: bool = False,
        allow_redirects: bool = True,
        enable_cf_bypass: bool = True,
        retry_count: int | None = None,
    ) -> tuple[Response | None, str]:
        """
        执行请求的通用方法

        Args:
            url: 请求URL
            headers: 请求头
            cookies: cookies
            use_proxy: 是否使用代理
            data: 表单数据
            json_data: JSON数据
            timeout: 请求超时时间, 覆盖客户端默认值

        Returns:
            tuple[Optional[Response], str]: (响应对象, 错误信息)
        """
        try:
            original_url = url
            url, sanitized = self._sanitize_url(url)
            if sanitized:
                self._log(f"⚠️ 检测到异常 URL，已清理: {original_url} -> {url}")

            u = httpx.URL(url)
            host = u.host or ""
            prepared_headers = self._prepare_headers(url, dict(headers or {}))
            limiter = self.limiters.get(u.host)
            request_proxy = self.proxy if use_proxy else None
            pool_key = HostPoolManager.key_for_url(url, request_proxy)
            retry_count = max(int(self.retry if retry_count is None else retry_count), 1)
            error_msg = ""
            bypass_round = 0

            for attempt in range(retry_count):
                # 增强的重试策略: 对网络错误和特定状态码都进行重试
                retry = False
                should_sleep_before_retry = True
                sleep_after_cf_bypass = False
                resp: Response | None = None
                try:
                    await limiter.acquire()
                    req_headers = dict(prepared_headers)
                    req_cookies = self._merge_cookies(cookies)
                    host_retry_semaphore = None
                    if host and self._cf_host_challenge_hits.get(host, 0) > 0:
                        host_retry_semaphore = await self._get_cf_host_retry_semaphore(host)
                    if host_retry_semaphore is not None:
                        async with host_retry_semaphore:
                            resp = await self._curl_request(
                                method=method,
                                url=url,
                                proxy=request_proxy,
                                headers=req_headers,
                                cookies=req_cookies,
                                params=params,
                                data=data,
                                json=json_data,
                                timeout=timeout or not_set,
                                stream=stream,
                                allow_redirects=allow_redirects,
                            )
                    else:
                        resp = await self._curl_request(
                            method=method,
                            url=url,
                            proxy=request_proxy,
                            headers=req_headers,
                            cookies=req_cookies,
                            params=params,
                            data=data,
                            json=json_data,
                            timeout=timeout or not_set,
                            stream=stream,
                            allow_redirects=allow_redirects,
                        )

                    if enable_cf_bypass and self._cf_bypass_enabled and host and self._is_cf_challenge_response(resp):
                        self._log_cf(f"🛑 检测到 Cloudflare 挑战页: {method} {url}", host)
                        self._cf_host_challenge_hits[host] = self._cf_host_challenge_hits.get(host, 0) + 1
                        if bypass_round >= self._cf_request_bypass_rounds:
                            error_msg = f"Cloudflare 挑战页持续存在，bypass 已达上限 ({self._cf_request_bypass_rounds})"
                            retry = False
                            self._log_cf(f"🚫 {error_msg}", host)
                        else:
                            target_url = self._merge_url_params(url, params)
                            bypass_response, bypass_error = await self._try_bypass_cloudflare(
                                host=host,
                                method=method,
                                target_url=target_url,
                                headers=req_headers,
                                cookies=req_cookies,
                                data=data,
                                json_data=json_data,
                                timeout=timeout,
                                allow_redirects=allow_redirects,
                                use_proxy=bool((self.cf_bypass_proxy or "").strip()),
                            )
                            bypass_round += 1

                            if bypass_response is not None:
                                bypass_mode = self._extract_header_case_insensitive(
                                    {str(k): str(v) for k, v in bypass_response.headers.items()},
                                    "x-mdcx-bypass-mode",
                                )
                                if bypass_response.status_code >= 300 and not (
                                    bypass_response.status_code == 302
                                    and self._extract_header_case_insensitive(
                                        {str(k): str(v) for k, v in bypass_response.headers.items()}, "location"
                                    )
                                ):
                                    error_msg = (
                                        f"HTTP {bypass_response.status_code} (bypass:{bypass_mode or 'unknown'})"
                                    )
                                    retry = attempt < retry_count - 1 and self._is_retryable_status_code(
                                        bypass_response.status_code
                                    )
                                    self._log_cf(
                                        f"⚠️ bypass 返回非成功状态: {error_msg}，将{'重试' if retry else '停止重试'}",
                                        host,
                                    )
                                else:
                                    self._log_cf(
                                        f"✅ bypass 成功（模式: {bypass_mode or 'unknown'}），直接使用 bypass 响应",
                                        host,
                                    )
                                    if stream:
                                        await self._close_response(resp)
                                    return bypass_response, ""
                            else:
                                error_msg = f"Cloudflare 挑战页且 bypass 失败: {bypass_error}"
                                terminal_status = self._extract_terminal_bypass_status(bypass_error)
                                if terminal_status is not None and not self._is_retryable_status_code(terminal_status):
                                    retry = False
                                    self._log_cf(f"🧱 bypass 命中终态 HTTP {terminal_status}，停止重试", host)
                                else:
                                    retry = attempt < retry_count - 1 and bypass_round < self._cf_request_bypass_rounds
                                    self._log_cf(f"⚠️ bypass 失败: {bypass_error}", host)

                    # 检查响应状态
                    elif resp.status_code >= 300 and not (resp.status_code == 302 and resp.headers.get("Location")):
                        error_msg = f"HTTP {resp.status_code}"
                        retry = self._is_retryable_status_code(resp.status_code)
                    else:
                        self._log(f"✅ {method} {url} 成功")
                        if host:
                            self._cf_host_challenge_hits[host] = 0
                        await self._record_transport_success(pool_key=pool_key)
                        return resp, ""
                except Timeout:
                    error_msg = "连接超时"
                    retry = True  # 超时错误进行重试
                    await self._record_transport_failure(error_msg, pool_key=pool_key)
                except ConnectionError as e:
                    error_msg = f"连接错误: {str(e)}"
                    retry = True  # 连接错误进行重试
                    await self._record_transport_failure(error_msg, pool_key=pool_key)
                except RequestException as e:
                    error_msg = f"请求异常: {str(e)} {getattr(e, 'code', '')}".strip()
                    retry = True  # 请求异常进行重试
                    await self._record_transport_failure(error_msg, pool_key=pool_key)
                except TimeoutError:
                    error_msg = "请求等待超时"
                    retry = True
                    await self._record_transport_failure(error_msg, pool_key=pool_key)
                except Exception as e:
                    error_msg = f"curl-cffi 异常: {str(e)}"
                    retry = True
                    await self._record_transport_failure(error_msg, pool_key=pool_key)
                if not retry:
                    if stream:
                        await self._close_response(resp)
                    break
                self._log(f"🔴 {method} {url} 失败: {error_msg} ({attempt + 1}/{retry_count})")
                if stream:
                    await self._close_response(resp)
                # 重试前等待
                if should_sleep_before_retry and attempt < retry_count - 1:
                    sleep_seconds = self._calc_retry_sleep_seconds(attempt, after_cf_bypass=sleep_after_cf_bypass)
                    if sleep_after_cf_bypass and host:
                        self._log_cf(f"⏳ bypass 后退避 {sleep_seconds:.2f}s", host)
                    await asyncio.sleep(sleep_seconds)
            return None, f"{method} {url} 失败: {error_msg}"
        except Exception as e:
            error_msg = f"{method} {url} 未知错误:  {str(e)}"
            self._log(f"🔴 {error_msg}")
            return None, error_msg

    async def get_text(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        encoding: str = "utf-8",
        use_proxy: bool = True,
        retry_count: int | None = None,
    ) -> tuple[str | None, str]:
        """请求文本内容"""
        resp, error = await self.request(
            "GET", url, headers=headers, cookies=cookies, use_proxy=use_proxy, retry_count=retry_count
        )
        if resp is None:
            return None, error
        try:
            resp.encoding = encoding
            return resp.text, error
        except Exception as e:
            return None, f"文本解析失败: {str(e)}"

    async def get_content(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        use_proxy: bool = True,
        retry_count: int | None = None,
    ) -> tuple[bytes | None, str]:
        """请求二进制内容"""
        resp, error = await self.request(
            "GET", url, headers=headers, cookies=cookies, use_proxy=use_proxy, retry_count=retry_count
        )
        if resp is None:
            return None, error

        return resp.content, ""

    async def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        use_proxy: bool = True,
        retry_count: int | None = None,
    ) -> tuple[Any | None, str]:
        """请求JSON数据"""
        response, error = await self.request(
            "GET", url, headers=headers, cookies=cookies, use_proxy=use_proxy, retry_count=retry_count
        )
        if response is None:
            return None, error
        try:
            return response.json(), ""
        except Exception as e:
            return None, f"JSON解析失败: {str(e)}"

    async def post_text(
        self,
        url: str,
        *,
        data: dict[str, str] | list[tuple] | str | BytesIO | bytes | None = None,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        encoding: str = "utf-8",
        use_proxy: bool = True,
        retry_count: int | None = None,
    ) -> tuple[str | None, str]:
        """POST 请求, 返回响应文本内容"""
        response, error = await self.request(
            "POST",
            url,
            data=data,
            json_data=json_data,
            headers=headers,
            cookies=cookies,
            use_proxy=use_proxy,
            retry_count=retry_count,
        )
        if response is None:
            return None, error
        try:
            response.encoding = encoding
            return response.text, ""
        except Exception as e:
            return None, f"文本解析失败: {str(e)}"

    async def post_json(
        self,
        url: str,
        *,
        data: dict[str, str] | list[tuple] | str | BytesIO | bytes | None = None,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        use_proxy: bool = True,
        retry_count: int | None = None,
    ) -> tuple[Any | None, str]:
        """POST 请求, 返回响应JSON数据"""
        response, error = await self.request(
            "POST",
            url,
            data=data,
            json_data=json_data,
            headers=headers,
            cookies=cookies,
            use_proxy=use_proxy,
            retry_count=retry_count,
        )
        if error or response is None:
            return None, error

        try:
            return response.json(), ""
        except Exception as e:
            return None, f"JSON解析失败: {str(e)}"

    async def post_content(
        self,
        url: str,
        *,
        data: dict[str, str] | list[tuple] | str | BytesIO | bytes | None = None,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        use_proxy: bool = True,
        retry_count: int | None = None,
    ) -> tuple[bytes | None, str]:
        """POST请求, 返回二进制响应"""
        response, error = await self.request(
            "POST",
            url,
            data=data,
            json_data=json_data,
            headers=headers,
            cookies=cookies,
            use_proxy=use_proxy,
            retry_count=retry_count,
        )
        if error or response is None:
            return None, error

        return response.content, ""

    async def get_filesize(self, url: str, *, use_proxy: bool = True) -> int | None:
        """获取文件大小"""
        response, error = await self.request("HEAD", url, use_proxy=use_proxy)
        if response is None:
            self._log(f"🔴 获取文件大小失败: {url} {error}")
            return None
        if response.status_code < 400:
            content_length = self._extract_header_case_insensitive(
                {str(k): str(v) for k, v in response.headers.items()}, "content-length"
            )
            if not content_length:
                return None
            try:
                return int(content_length)
            except ValueError:
                self._log(f"🔴 获取文件大小失败: {url} Content-Length 解析错误")
                return None
        self._log(f"🔴 获取文件大小失败: {url} HTTP {response.status_code}")
        return None

    async def download(self, url: str, file_path: Path, *, use_proxy: bool = True) -> bool:
        """
        下载文件. 当文件较大时分块下载

        Args:
            url: 下载链接
            file_path: 保存路径
            use_proxy: 是否使用代理

        Returns:
            bool: 下载是否成功
        """
        # 获取文件大小
        file_size = None if self._is_dmm_image_url(url) else await self.get_filesize(url, use_proxy=use_proxy)
        # 判断是不是webp文件
        webp = False
        if file_path.suffix == "jpg" and ".webp" in url:
            webp = True

        MB = 1024**2
        # 2 MB 以上使用分块下载, 不清楚为什么 webp 不分块, 可能是因为要转换成 jpg
        if file_size and file_size > 2 * MB and not webp:
            return await self._download_chunks(url, file_path, file_size, use_proxy)

        content, error = await self.get_content(url, use_proxy=use_proxy)
        if not content:
            self._log(f"🔴 下载失败: {url} {error}")
            return False
        if not webp:
            return await self._write_file_content(url, file_path, content)
        try:
            byte_stream = BytesIO(content)
            img: Image.Image = Image.open(byte_stream)
            if img.mode == "RGBA":
                img = img.convert("RGB")
            img.save(file_path, quality=95, subsampling=0)
            img.close()
            return True
        except Exception as e:
            self._log(f"🔴 WebP转换失败: {url} {file_path} {str(e)}")
            return False

    async def _write_file_content(self, url: str, file_path: Path, content: bytes) -> bool:
        try:
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(content)
            return True
        except Exception as e:
            self._log(f"🔴 文件写入失败: {url} {file_path} {str(e)}")
            return False

    async def _download_whole_file(
        self,
        url: str,
        file_path: Path,
        *,
        use_proxy: bool,
        expected_size: int | None = None,
    ) -> bool:
        content, error = await self.get_content(url, use_proxy=use_proxy)
        if not content:
            self._log(f"🔴 下载失败: {url} {error}")
            return False
        if expected_size is not None and len(content) != expected_size:
            self._log(f"🔴 下载大小不匹配: {url} {len(content)}/{expected_size}")
            return False
        return await self._write_file_content(url, file_path, content)

    async def _download_chunks(self, url: str, file_path: Path, file_size: int, use_proxy: bool = True) -> bool:
        """分块下载大文件"""
        # 分块，每块 1 MB
        MB = 1024**2
        each_size = min(1 * MB, file_size)
        parts = [(s, min(s + each_size, file_size)) for s in range(0, file_size, each_size)]

        self._log(f"📦 分块下载: {url} {len(parts)} 个分块, 总大小: {file_size} bytes")

        # 先创建文件并预分配空间
        try:
            async with aiofiles.open(file_path, "wb") as f:
                await f.truncate(file_size)
        except Exception as e:
            self._log(f"🔴 文件创建失败: {url} {str(e)}")
            return False

        # 创建下载任务
        semaphore = asyncio.Semaphore(10)  # 限制并发数
        first_start, first_end = parts[0]
        first_error = await self._download_chunk(semaphore, url, file_path, first_start, first_end, 0, use_proxy)
        if first_error:
            if self._is_range_unsupported_error(first_error):
                self._log(f"🟡 服务器不支持分块下载，回退普通下载: {url}")
                return await self._download_whole_file(url, file_path, use_proxy=use_proxy, expected_size=file_size)
            self._log(f"🔴 分块 0 下载失败: {url} {first_error}")
            return False

        tasks = []

        for i, (start, end) in enumerate(parts[1:], start=1):
            task = self._download_chunk(semaphore, url, file_path, start, end, i, use_proxy)
            tasks.append(task)

        # 并发执行所有下载任务
        try:
            errors = await asyncio.gather(*tasks, return_exceptions=True)
            # 检查所有任务是否成功
            for i, err in enumerate(errors):
                if isinstance(err, Exception):
                    self._log(f"🔴 分块 {i} 下载失败: {url} {str(err)}")
                    return False
                elif err:
                    self._log(f"🔴 分块 {i} 下载失败: {url} {err}")
                    return False
            self._log(f"✅ 多分块下载完成: {url} {file_path}")
            return True
        except Exception as e:
            self._log(f"🔴 并发下载异常: {url} {str(e)}")
            return False

    def _is_range_unsupported_error(self, error: str) -> bool:
        return "分块响应状态异常: HTTP 200" in str(error or "")

    async def _download_chunk(
        self,
        semaphore: asyncio.Semaphore,
        url: str,
        file_path: Path,
        start: int,
        end: int,
        chunk_id: int,
        use_proxy: bool = True,
    ) -> str | None:
        """下载单个分块"""
        retry_count = max(int(self.retry), 1)
        last_error = ""
        for attempt in range(retry_count):
            async with semaphore:
                success, last_error = await self._download_chunk_once(url, file_path, start, end, use_proxy)
                if success:
                    return ""

            if attempt < retry_count - 1:
                await asyncio.sleep(self._calc_retry_sleep_seconds(attempt))

        return last_error

    async def _download_chunk_once(
        self,
        url: str,
        file_path: Path,
        start: int,
        end: int,
        use_proxy: bool,
    ) -> tuple[bool, str]:
        expected_size = end - start + 1
        res, error = await self.request(
            "GET",
            url,
            headers={"Range": f"bytes={start}-{end}"},
            use_proxy=use_proxy,
            stream=True,
            retry_count=1,
        )
        if res is None:
            return False, error
        try:
            if res.status_code != 206:
                return False, f"分块响应状态异常: HTTP {res.status_code}"
            content = await res.acontent()
            if len(content) != expected_size:
                return False, f"分块大小不匹配: {len(content)}/{expected_size}"
            async with aiofiles.open(file_path, "rb+") as fp:
                await fp.seek(start)
                await fp.write(content)
            return True, ""
        except Exception as exc:
            error = f"读取分块响应失败: {exc}"
            pool_key = HostPoolManager.key_for_url(url, self.proxy if use_proxy else None)
            await self._record_transport_failure(error, pool_key=pool_key)
            return False, error
        finally:
            await self._close_response(res)
