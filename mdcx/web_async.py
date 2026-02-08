import asyncio
import random
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
        self._cf_host_locks: dict[str, asyncio.Lock] = {}
        self._cf_locks_guard = asyncio.Lock()
        self._cf_last_refresh_at: dict[str, float] = {}
        self._cf_host_challenge_hits: dict[str, int] = {}
        self._cf_bypass_cooldown = 30.0
        self._cf_bypass_timeout = 45.0
        self._cf_cookie_retries = 2
        self._cf_force_refresh_retries = 2

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

    def _extract_header_case_insensitive(self, headers: dict[str, Any], key: str) -> str:
        key_lower = key.lower()
        for k, v in headers.items():
            if str(k).lower() == key_lower:
                return str(v)
        return ""

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
        if (status in (403, 429, 503) and ("cloudflare" in server or bool(cf_ray)) and has_marker):
            return True
        # 规则2: 挑战文案足够明确时，允许无 header 命中
        if has_marker and ("cf-chl" in body_text or "cdn-cgi/challenge-platform" in body_text):
            return True
        return False

    def _extract_bypass_payload(self, payload: Any) -> tuple[dict[str, str], str]:
        if not isinstance(payload, dict):
            return {}, ""
        cookies = payload.get("cookies")
        if not isinstance(cookies, dict):
            cookies = {}
        cookies = {str(k): str(v) for k, v in cookies.items() if k and v is not None}

        user_agent = payload.get("user_agent")
        if user_agent is None:
            user_agent = payload.get("userAgent", "")
        if not isinstance(user_agent, str):
            user_agent = ""
        return cookies, user_agent.strip()

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
                    self._log(f"⚠️ bypass 强刷失败 ({i + 1}/{self._cf_force_refresh_retries}): {refresh_err}")
                    continue
                if refresh_resp.status_code >= 400:
                    self._log(
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
                self._log(f"⚠️ bypass cookies 获取失败 ({i + 1}/{self._cf_cookie_retries}): {error}")
                continue
            if response.status_code >= 400:
                err = f"HTTP {response.status_code}"
                self._log(f"⚠️ bypass cookies 获取失败 ({i + 1}/{self._cf_cookie_retries}): {err}")
                continue
            try:
                payload = response.json()
            except Exception as e:
                err = f"JSON 解析失败: {e}"
                self._log(f"⚠️ bypass cookies 获取失败 ({i + 1}/{self._cf_cookie_retries}): {err}")
                continue
            cookies, user_agent = self._extract_bypass_payload(payload)
            if cookies.get("cf_clearance"):
                return cookies, user_agent, ""
            if cookies:
                self._log(f"⚠️ bypass cookies 缺少 cf_clearance ({i + 1}/{self._cf_cookie_retries})")
            if i < self._cf_cookie_retries - 1:
                self._log(f"⚠️ bypass cookies 为空，准备重试 ({i + 1}/{self._cf_cookie_retries})")
        return {}, "", "bypass 返回 cookies 无效或为空"

    async def _try_bypass_cloudflare(
        self,
        *,
        host: str,
        target_url: str,
        use_proxy: bool,
    ) -> tuple[dict[str, str], str, str]:
        lock = await self._get_cf_host_lock(host)
        async with lock:
            now = time.monotonic()
            last = self._cf_last_refresh_at.get(host, 0)
            challenge_hits = self._cf_host_challenge_hits.get(host, 0)
            force_refresh = (now - last >= self._cf_bypass_cooldown) or challenge_hits >= 2

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
                self._log(f"🔐 {host} 向 bypass 请求 cookies: {bypass_target}")
                cookies, user_agent, error = await self._call_bypass_cookies(
                    bypass_target,
                    force_refresh=False,
                    use_proxy=use_proxy,
                )
                if cookies:
                    self._cf_host_cookies[host] = cookies
                    if user_agent:
                        self._cf_host_user_agents[host] = user_agent
                    self._cf_last_refresh_at[host] = time.monotonic()
                    return cookies, user_agent, ""

            if force_refresh:
                for bypass_target in bypass_targets:
                    self._log(f"🧨 {host} bypass cookies 无效，强制刷新: {bypass_target}")
                    cookies, user_agent, error = await self._call_bypass_cookies(
                        bypass_target,
                        force_refresh=True,
                        use_proxy=use_proxy,
                    )
                    if cookies:
                        self._cf_host_cookies[host] = cookies
                        if user_agent:
                            self._cf_host_user_agents[host] = user_agent
                        self._cf_last_refresh_at[host] = time.monotonic()
                        return cookies, user_agent, ""

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
            u = httpx.URL(url)
            host = u.host or ""
            prepared_headers = self._prepare_headers(url, dict(headers or {}))
            if host and host in self._cf_host_user_agents and all(k.lower() != "user-agent" for k in prepared_headers):
                prepared_headers["User-Agent"] = self._cf_host_user_agents[host]

            await self.limiters.get(u.host).acquire()
            retry_count = self.retry
            error_msg = ""

            if enable_cf_bypass and self._cf_bypass_enabled and host and host in self._cf_host_cookies:
                self._log(f"🍪 {host} 使用缓存 bypass cookies")

            for attempt in range(retry_count):
                # 增强的重试策略: 对网络错误和特定状态码都进行重试
                retry = False
                should_sleep_before_retry = True
                try:
                    req_headers = dict(prepared_headers)
                    req_cookies = self._merge_cookies(cookies, host)
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

                    if enable_cf_bypass and self._cf_bypass_enabled and host and self._is_cf_challenge_response(resp):
                        self._log(f"🛑 检测到 Cloudflare 挑战页: {method} {url}")
                        self._cf_host_challenge_hits[host] = self._cf_host_challenge_hits.get(host, 0) + 1
                        bypass_cookies, bypass_user_agent, bypass_error = await self._try_bypass_cloudflare(
                            host=host,
                            target_url=url,
                            use_proxy=False,
                        )
                        if bypass_cookies:
                            retry = True
                            should_sleep_before_retry = False
                            error_msg = "Cloudflare challenge"
                            if bypass_user_agent and all(k.lower() != "user-agent" for k in prepared_headers):
                                prepared_headers["User-Agent"] = bypass_user_agent
                            self._log(f"🛡️ {host} bypass 成功，准备立即重试")
                            self._cf_host_challenge_hits[host] = 0
                        else:
                            error_msg = f"Cloudflare challenge and bypass failed: {bypass_error}"
                            retry = attempt < retry_count - 1
                            self._log(f"⚠️ {host} bypass 失败: {bypass_error}")

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
                    await asyncio.sleep(attempt * 3 + 2)
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
