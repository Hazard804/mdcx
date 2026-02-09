import asyncio
import random
import re
import sys
import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

import aiofiles
import httpx
from aiolimiter import AsyncLimiter
from curl_cffi import AsyncSession, Response
from curl_cffi.requests.exceptions import ConnectionError, RequestException, Timeout
from curl_cffi.requests.session import HttpMethod
from curl_cffi.requests.utils import not_set
from PIL import Image


class AsyncWebLimiters:
    def __init__(self):
        self.limiters: dict[str, AsyncLimiter] = {
            "127.0.0.1": AsyncLimiter(300, 1),
            "localhost": AsyncLimiter(300, 1),
        }

    def get(self, key: str, rate: float = 5, period: float = 1) -> AsyncLimiter:
        """默认对所有域名启用 5 req/s 的速率限制"""
        return self.limiters.setdefault(key, AsyncLimiter(rate, period))

    def remove(self, key: str):
        if key in self.limiters:
            del self.limiters[key]


class AsyncWebClient:
    def __init__(
        self,
        *,
        proxy: str | None = None,
        retry: int = 3,
        timeout: float,
        cf_bypass_url: str = "",
        log_fn: Callable[[str], None] | None = None,
        limiters: AsyncWebLimiters | None = None,
        loop=None,
    ):
        self.retry = retry
        self.proxy = proxy
        self.curl_session = AsyncSession(
            loop=loop,
            max_clients=50,
            verify=False,
            max_redirects=20,
            timeout=timeout,
            impersonate=random.choice(["chrome123", "chrome124", "chrome131", "chrome136", "firefox133", "firefox135"]),
        )

        self.log_fn = log_fn if log_fn is not None else lambda _: None
        self.limiters = limiters if limiters is not None else AsyncWebLimiters()

        self.cf_bypass_url = cf_bypass_url.strip().rstrip("/")
        self._cf_bypass_enabled = bool(self.cf_bypass_url)
        self._cf_host_cookies: dict[str, dict[str, str]] = {}
        self._cf_host_user_agents: dict[str, str] = {}
        self._cf_cookie_user_agent_bindings: dict[str, dict[str, str]] = {}
        self._cf_cookie_user_agent_binding_timestamps: dict[str, dict[str, float]] = {}
        self._cf_cookie_binding_ttl = 3600.0
        self._cf_cookie_binding_max_entries_per_host = 32
        self._cf_cookie_binding_max_entries_total = 256
        self._cf_host_locks: dict[str, asyncio.Lock] = {}
        self._cf_host_retry_semaphores: dict[str, asyncio.Semaphore] = {}
        self._cf_locks_guard = asyncio.Lock()
        self._cf_last_refresh_at: dict[str, float] = {}
        self._cf_host_challenge_hits: dict[str, int] = {}
        self._cf_bypass_cooldown = 30.0
        self._cf_recent_refresh_window = 10.0
        self._cf_force_refresh_min_interval = 10.0
        self._cf_bypass_timeout = 45.0
        self._cf_cookie_retries = 2
        self._cf_force_refresh_retries = 2
        self._cf_request_bypass_rounds = 2
        self._cf_retry_max_concurrent_per_host = 2
        self._cf_retry_after_bypass_base_delay = 1.2
        self._cf_retry_after_bypass_jitter = 1.3
        self._retry_sleep_jitter = 0.4

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
        host: str,
        bypass_cookies: dict[str, str] | None = None,
    ) -> dict[str, str] | None:
        base = dict(cookies or {})
        cached = self._cf_host_cookies.get(host)
        if cached:
            base.update(cached)
        if bypass_cookies:
            base.update(bypass_cookies)
        return base or None

    def _build_cf_cookie_binding_key(self, cookies: dict[str, str] | None) -> str:
        if not cookies:
            return ""

        cf_clearance = str(cookies.get("cf_clearance", "")).strip()
        if cf_clearance:
            return f"cf_clearance={cf_clearance}"

        pairs = sorted((str(k), str(v)) for k, v in cookies.items() if k and v is not None)
        if not pairs:
            return ""
        return "&".join(f"{k}={v}" for k, v in pairs)

    def _remember_cf_cookie_user_agent(self, host: str, cookies: dict[str, str] | None, user_agent: str) -> None:
        if not host:
            return

        normalized_user_agent = (user_agent or "").strip()
        if not normalized_user_agent:
            return

        binding_key = self._build_cf_cookie_binding_key(cookies)
        if not binding_key:
            return

        host_bindings = self._cf_cookie_user_agent_bindings.setdefault(host, {})
        host_binding_timestamps = self._cf_cookie_user_agent_binding_timestamps.setdefault(host, {})
        host_bindings[binding_key] = normalized_user_agent
        host_binding_timestamps[binding_key] = time.monotonic()
        self._prune_cf_cookie_user_agent_bindings_for_host(host)
        self._prune_cf_cookie_user_agent_bindings_global()

    def _prune_cf_cookie_user_agent_bindings_for_host(self, host: str) -> None:
        if not host:
            return

        host_bindings = self._cf_cookie_user_agent_bindings.get(host)
        if not host_bindings:
            self._cf_cookie_user_agent_bindings.pop(host, None)
            self._cf_cookie_user_agent_binding_timestamps.pop(host, None)
            return

        host_binding_timestamps = self._cf_cookie_user_agent_binding_timestamps.setdefault(host, {})
        now = time.monotonic()
        ttl = max(0.0, float(self._cf_cookie_binding_ttl))
        removed_expired = 0
        removed_overflow = 0

        if ttl > 0:
            for binding_key in list(host_bindings):
                ts = host_binding_timestamps.get(binding_key)
                if ts is None:
                    host_binding_timestamps[binding_key] = now
                    ts = now
                if now - ts > ttl:
                    host_bindings.pop(binding_key, None)
                    host_binding_timestamps.pop(binding_key, None)
                    removed_expired += 1

        max_entries_per_host = max(int(self._cf_cookie_binding_max_entries_per_host), 1)
        overflow = len(host_bindings) - max_entries_per_host
        if overflow > 0:
            ordered_keys = sorted(host_bindings, key=lambda key: host_binding_timestamps.get(key, 0.0))
            for binding_key in ordered_keys[:overflow]:
                host_bindings.pop(binding_key, None)
                host_binding_timestamps.pop(binding_key, None)
                removed_overflow += 1

        if not host_bindings:
            self._cf_cookie_user_agent_bindings.pop(host, None)
            self._cf_cookie_user_agent_binding_timestamps.pop(host, None)

        if removed_expired or removed_overflow:
            self._log_cf(f"🧹 清理 cookie-UA 绑定: 过期 {removed_expired}，超限 {removed_overflow}", host)

    def _prune_cf_cookie_user_agent_bindings_global(self) -> None:
        max_entries_total = max(int(self._cf_cookie_binding_max_entries_total), 1)

        all_entries: list[tuple[float, str, str]] = []
        now = time.monotonic()
        for host, host_bindings in self._cf_cookie_user_agent_bindings.items():
            host_binding_timestamps = self._cf_cookie_user_agent_binding_timestamps.setdefault(host, {})
            for binding_key in host_bindings:
                ts = host_binding_timestamps.get(binding_key)
                if ts is None:
                    host_binding_timestamps[binding_key] = now
                    ts = now
                all_entries.append((ts, host, binding_key))

        overflow = len(all_entries) - max_entries_total
        if overflow <= 0:
            return

        all_entries.sort(key=lambda item: item[0])
        removed = 0
        touched_hosts: set[str] = set()
        for _, host, binding_key in all_entries[:overflow]:
            host_bindings = self._cf_cookie_user_agent_bindings.get(host)
            host_binding_timestamps = self._cf_cookie_user_agent_binding_timestamps.get(host)
            if not host_bindings or not host_binding_timestamps:
                continue

            if binding_key in host_bindings:
                host_bindings.pop(binding_key, None)
                host_binding_timestamps.pop(binding_key, None)
                removed += 1
                touched_hosts.add(host)

            if not host_bindings:
                self._cf_cookie_user_agent_bindings.pop(host, None)
                self._cf_cookie_user_agent_binding_timestamps.pop(host, None)

        if removed > 0:
            self._log_cf(f"🧹 全局清理 cookie-UA 绑定: 移除 {removed} 条，涉及主机 {len(touched_hosts)}")

    def _resolve_cf_cookie_user_agent(self, host: str, cookies: dict[str, str] | None) -> str:
        if not host:
            return ""

        self._prune_cf_cookie_user_agent_bindings_for_host(host)

        binding_key = self._build_cf_cookie_binding_key(cookies)
        if not binding_key:
            return ""

        return self._cf_cookie_user_agent_bindings.get(host, {}).get(binding_key, "").strip()

    def _clear_cf_host_binding(self, host: str) -> None:
        if not host:
            return
        self._cf_host_cookies.pop(host, None)
        self._cf_host_user_agents.pop(host, None)

    def _apply_cf_host_binding(self, host: str, cookies: dict[str, str], user_agent: str) -> str:
        resolved_user_agent = (user_agent or "").strip()
        if not resolved_user_agent:
            resolved_user_agent = self._resolve_cf_cookie_user_agent(host, cookies)
            if resolved_user_agent:
                self._log_cf("♻️ bypass 未返回 UA，复用已绑定 cookie-UA", host)

        self._cf_host_cookies[host] = cookies
        if resolved_user_agent:
            self._cf_host_user_agents[host] = resolved_user_agent
            self._remember_cf_cookie_user_agent(host, cookies, resolved_user_agent)
        else:
            self._cf_host_user_agents.pop(host, None)

        self._cf_last_refresh_at[host] = time.monotonic()
        self._cf_host_challenge_hits[host] = 0
        return resolved_user_agent

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

    def _sanitize_url(self, url: str) -> tuple[str, bool]:
        cleaned = (url or "").strip()
        if not cleaned:
            return cleaned, False
        # 过滤类似 https://x.com?a=1">https://x.com?a=1 这类污染字符串
        match = re.match(r"^(https?://[^\s\"'<>]+)", cleaned)
        if not match:
            return cleaned, False
        normalized = match.group(1)
        return normalized, normalized != cleaned

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

    def _extract_bypass_payload(self, payload: Any) -> tuple[dict[str, str], str]:
        if not isinstance(payload, dict):
            return {}, ""

        candidates: list[dict[str, Any]] = [payload]
        for key in ("data", "result", "payload"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                candidates.append(nested)

        cookies: dict[str, str] = {}
        for item in candidates:
            raw_cookies = item.get("cookies")
            if not isinstance(raw_cookies, dict):
                continue
            cookies = {str(k): str(v) for k, v in raw_cookies.items() if k and v is not None}
            if cookies:
                break

        user_agent = ""
        for item in candidates:
            for key in ("user_agent", "userAgent", "ua", "browser_user_agent", "browserUserAgent"):
                ua_value = item.get(key)
                if isinstance(ua_value, str) and ua_value.strip():
                    user_agent = ua_value.strip()
                    break
            if user_agent:
                break

            for key in ("headers", "request_headers", "requestHeaders"):
                raw_headers = item.get(key)
                if not isinstance(raw_headers, dict):
                    continue
                header_user_agent = self._extract_header_case_insensitive(raw_headers, "user-agent").strip()
                if header_user_agent:
                    user_agent = header_user_agent
                    break
            if user_agent:
                break

        return cookies, user_agent

    async def _call_bypass_cookies(
        self,
        target_url: str,
        *,
        force_refresh: bool,
        use_proxy: bool,
    ) -> tuple[dict[str, str], str, str]:
        if not self._cf_bypass_enabled:
            return {}, "", "未配置 bypass 地址"

        params = {"url": target_url}
        if force_refresh:
            refresh_url = f"{self.cf_bypass_url}/cache/refresh"
            for i in range(self._cf_force_refresh_retries):
                refresh_resp, refresh_err = await self.request(
                    "POST",
                    refresh_url,
                    use_proxy=use_proxy,
                    allow_redirects=True,
                    timeout=self._cf_bypass_timeout,
                    params=params,
                    enable_cf_bypass=False,
                )
                if refresh_resp is None:
                    self._log_cf(f"⚠️ bypass 强刷失败 ({i + 1}/{self._cf_force_refresh_retries}): {refresh_err}")
                    continue
                if refresh_resp.status_code >= 400:
                    self._log_cf(
                        f"⚠️ bypass 强刷失败 ({i + 1}/{self._cf_force_refresh_retries}): HTTP {refresh_resp.status_code}"
                    )
                    continue
                break

        bypass_url = f"{self.cf_bypass_url}/cookies"
        for i in range(self._cf_cookie_retries):
            response, error = await self.request(
                "GET",
                bypass_url,
                use_proxy=use_proxy,
                allow_redirects=True,
                timeout=self._cf_bypass_timeout,
                params=params,
                enable_cf_bypass=False,
            )
            if response is None:
                self._log_cf(f"⚠️ bypass cookies 获取失败 ({i + 1}/{self._cf_cookie_retries}): {error}")
                continue
            if response.status_code >= 400:
                err = f"HTTP {response.status_code}"
                self._log_cf(f"⚠️ bypass cookies 获取失败 ({i + 1}/{self._cf_cookie_retries}): {err}")
                continue
            try:
                payload = response.json()
            except Exception as e:
                err = f"JSON 解析失败: {e}"
                self._log_cf(f"⚠️ bypass cookies 获取失败 ({i + 1}/{self._cf_cookie_retries}): {err}")
                continue
            cookies, user_agent = self._extract_bypass_payload(payload)
            if cookies.get("cf_clearance"):
                return cookies, user_agent, ""
            if cookies:
                self._log_cf(f"⚠️ bypass cookies 缺少 cf_clearance ({i + 1}/{self._cf_cookie_retries})")
            if i < self._cf_cookie_retries - 1:
                self._log_cf(f"⚠️ bypass cookies 为空，准备重试 ({i + 1}/{self._cf_cookie_retries})")
        return {}, "", "bypass 返回 cookies 无效或为空"

    async def _try_bypass_cloudflare(
        self,
        *,
        host: str,
        target_url: str,
        use_proxy: bool,
        force_refresh: bool = False,
    ) -> tuple[dict[str, str], str, str]:
        lock = await self._get_cf_host_lock(host)
        async with lock:
            now = time.monotonic()
            last = self._cf_last_refresh_at.get(host, 0)
            cached_cookies = self._cf_host_cookies.get(host)
            cached_user_agent = self._cf_host_user_agents.get(host, "")

            # 单飞复用: 在并发场景下，后续请求复用刚刷新出来的 cookies，避免风暴
            if cached_cookies and not force_refresh and last > 0 and (now - last) <= self._cf_recent_refresh_window:
                self._log_cf("♻️ 复用最近刷新的 bypass cookies", host)
                return dict(cached_cookies), cached_user_agent, ""

            challenge_hits = self._cf_host_challenge_hits.get(host, 0)
            auto_force_refresh = (last > 0 and (now - last >= self._cf_bypass_cooldown)) or challenge_hits >= 2
            should_force_refresh = force_refresh or auto_force_refresh

            # 防止强刷风暴: 距离最近一次刷新过近时，优先复用缓存 cookies
            if (
                should_force_refresh
                and cached_cookies
                and last > 0
                and (now - last) <= self._cf_force_refresh_min_interval
            ):
                self._log_cf("🕒 距离上次刷新过近，跳过强刷并复用缓存 cookies", host)
                return dict(cached_cookies), cached_user_agent, ""

            bypass_targets: list[str] = []
            try:
                u = httpx.URL(target_url)
                if u.host:
                    origin = f"{u.scheme}://{u.host}"
                    if u.port and u.port not in (80, 443):
                        origin += f":{u.port}"
                    bypass_targets.append(origin)
            except Exception:
                pass
            bypass_targets.append(target_url)
            bypass_targets = list(dict.fromkeys(bypass_targets))

            error = ""
            for bypass_target in bypass_targets:
                if should_force_refresh:
                    self._log_cf(f"🧨 使用强刷模式请求 bypass cookies: {bypass_target}", host)
                self._log_cf(f"🔐 向 bypass 请求 cookies: {bypass_target}", host)
                cookies, user_agent, error = await self._call_bypass_cookies(
                    bypass_target,
                    force_refresh=should_force_refresh,
                    use_proxy=use_proxy,
                )
                if cookies:
                    resolved_user_agent = self._apply_cf_host_binding(host, cookies, user_agent)
                    return cookies, resolved_user_agent, ""

            if not should_force_refresh:
                for bypass_target in bypass_targets:
                    self._log_cf(f"🧨 bypass cookies 无效，强制刷新: {bypass_target}", host)
                    cookies, user_agent, error = await self._call_bypass_cookies(
                        bypass_target,
                        force_refresh=True,
                        use_proxy=use_proxy,
                    )
                    if cookies:
                        resolved_user_agent = self._apply_cf_host_binding(host, cookies, user_agent)
                        return cookies, resolved_user_agent, ""

            return {}, "", error

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
            host_bound_cookies = self._cf_host_cookies.get(host) if host else None
            if host and not host_bound_cookies and self._cf_host_user_agents.get(host):
                self._log_cf("⚠️ 检测到无 cookie 的 UA 绑定，已清理", host)
                self._cf_host_user_agents.pop(host, None)

            bound_user_agent = self._resolve_cf_cookie_user_agent(host, host_bound_cookies) if host else ""
            if not bound_user_agent and host and host_bound_cookies:
                fallback_bound_user_agent = self._cf_host_user_agents.get(host, "").strip()
                if fallback_bound_user_agent:
                    bound_user_agent = fallback_bound_user_agent
                    self._remember_cf_cookie_user_agent(host, host_bound_cookies, bound_user_agent)

            if bound_user_agent and host_bound_cookies:
                request_user_agent = self._extract_header_case_insensitive(prepared_headers, "user-agent")
                if request_user_agent.strip() and request_user_agent.strip() != bound_user_agent:
                    self._log_cf("🧩 使用 bypass 绑定 UA 覆盖请求头 UA", host)
                self._set_header_case_insensitive(prepared_headers, "User-Agent", bound_user_agent)

            limiter = self.limiters.get(u.host)
            retry_count = self.retry
            error_msg = ""
            bypass_round = 0
            force_refresh_used = False
            host_retry_semaphore = await self._get_cf_host_retry_semaphore(host) if host else None

            if enable_cf_bypass and self._cf_bypass_enabled and host and host in self._cf_host_cookies:
                self._log_cf("🍪 使用缓存 bypass cookies", host)

            for attempt in range(retry_count):
                # 增强的重试策略: 对网络错误和特定状态码都进行重试
                retry = False
                should_sleep_before_retry = True
                sleep_after_cf_bypass = False
                try:
                    await limiter.acquire()
                    req_headers = dict(prepared_headers)
                    req_cookies = self._merge_cookies(cookies, host)
                    if host_retry_semaphore is not None:
                        async with host_retry_semaphore:
                            resp: Response = await self.curl_session.request(
                                method,
                                url,
                                proxy=self.proxy if use_proxy else None,
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
                        resp = await self.curl_session.request(
                            method,
                            url,
                            proxy=self.proxy if use_proxy else None,
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
                            self._clear_cf_host_binding(host)
                            self._log_cf(f"🚫 {error_msg}", host)
                        else:
                            current_force_refresh = bypass_round > 0 and not force_refresh_used
                            if current_force_refresh:
                                self._log_cf("🧨 再次命中挑战，尝试强制刷新 bypass cookies", host)
                                self._clear_cf_host_binding(host)

                            bypass_cookies, bypass_user_agent, bypass_error = await self._try_bypass_cloudflare(
                                host=host,
                                target_url=url,
                                use_proxy=False,
                                force_refresh=current_force_refresh,
                            )
                            bypass_round += 1
                            if current_force_refresh:
                                force_refresh_used = True

                            if bypass_cookies:
                                retry = attempt < retry_count - 1
                                should_sleep_before_retry = True
                                sleep_after_cf_bypass = True
                                error_msg = "Cloudflare 挑战页"
                                if bypass_user_agent:
                                    self._set_header_case_insensitive(prepared_headers, "User-Agent", bypass_user_agent)
                                    self._log_cf("🧩 已应用 bypass 返回的 User-Agent", host)
                                else:
                                    self._log_cf("⚠️ bypass 未返回 User-Agent，仅使用 cookies 重试", host)
                                self._log_cf(
                                    f"✅ bypass 成功，准备重试 ({bypass_round}/{self._cf_request_bypass_rounds})", host
                                )
                            else:
                                error_msg = f"Cloudflare 挑战页且 bypass 失败: {bypass_error}"
                                retry = attempt < retry_count - 1 and bypass_round < self._cf_request_bypass_rounds
                                self._log_cf(f"⚠️ bypass 失败: {bypass_error}", host)

                    # 检查响应状态
                    elif resp.status_code >= 300 and not (resp.status_code == 302 and resp.headers.get("Location")):
                        error_msg = f"HTTP {resp.status_code}"
                        retry = resp.status_code in (
                            500,  # Internal Server Error
                            502,  # Bad Gateway
                            503,  # Service Unavailable
                            403,  # Forbidden
                            408,  # Request Timeout
                            429,  # Too Many Requests
                            504,  # Gateway Timeout
                        )
                    else:
                        self._log(f"✅ {method} {url} 成功")
                        if host:
                            self._cf_host_challenge_hits[host] = 0
                        return resp, ""
                except Timeout:
                    error_msg = "连接超时"
                    retry = True  # 超时错误进行重试
                except ConnectionError as e:
                    error_msg = f"连接错误: {str(e)}"
                    retry = True  # 连接错误进行重试
                except RequestException as e:
                    error_msg = f"请求异常: {str(e)} {e.code}"
                    retry = True  # 请求异常进行重试
                except Exception as e:
                    error_msg = f"curl-cffi 异常: {str(e)}"
                    retry = False  # 其他异常不重试，避免死循环
                if not retry:
                    break
                self._log(f"🔴 {method} {url} 失败: {error_msg} ({attempt + 1}/{retry_count})")
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
    ) -> tuple[str | None, str]:
        """请求文本内容"""
        resp, error = await self.request("GET", url, headers=headers, cookies=cookies, use_proxy=use_proxy)
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
    ) -> tuple[bytes | None, str]:
        """请求二进制内容"""
        resp, error = await self.request("GET", url, headers=headers, cookies=cookies, use_proxy=use_proxy)
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
    ) -> tuple[Any | None, str]:
        """请求JSON数据"""
        response, error = await self.request("GET", url, headers=headers, cookies=cookies, use_proxy=use_proxy)
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
    ) -> tuple[str | None, str]:
        """POST 请求, 返回响应文本内容"""
        response, error = await self.request(
            "POST", url, data=data, json_data=json_data, headers=headers, cookies=cookies, use_proxy=use_proxy
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
    ) -> tuple[Any | None, str]:
        """POST 请求, 返回响应JSON数据"""
        response, error = await self.request(
            "POST", url, data=data, json_data=json_data, headers=headers, cookies=cookies, use_proxy=use_proxy
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
    ) -> tuple[bytes | None, str]:
        """POST请求, 返回二进制响应"""
        response, error = await self.request(
            "POST", url, data=data, json_data=json_data, headers=headers, cookies=cookies, use_proxy=use_proxy
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
            try:
                return int(response.headers.get("Content-Length"))
            except (ValueError, TypeError):
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
        file_size = await self.get_filesize(url, use_proxy=use_proxy)
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
            try:
                async with aiofiles.open(file_path, "wb") as f:
                    await f.write(content)
                return True
            except Exception as e:
                self._log(f"🔴 文件写入失败: {url} {file_path} {str(e)}")
                return False
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
        tasks = []

        for i, (start, end) in enumerate(parts):
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
        async with semaphore:
            res, error = await self.request(
                "GET",
                url,
                headers={"Range": f"bytes={start}-{end}"},
                use_proxy=use_proxy,
                stream=True,
            )
            if res is None:
                return error
        # 写入文件
        async with aiofiles.open(file_path, "rb+") as fp:
            await fp.seek(start)
            await fp.write(await res.acontent())
        return ""
