import asyncio
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from urllib.parse import quote_plus, urljoin

from mdcx.config.enums import Website

if TYPE_CHECKING:
    from mdcx.web_async import AsyncWebClient


class NetworkCheckStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class NetworkCheckSpec:
    name: str
    group: str
    url: str
    site: Website | None = None
    method: str = "GET"
    use_proxy: bool = True
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    encoding: str = "utf-8"
    note: str = ""
    warning_if_missing: str = ""
    enable_cf_bypass: bool = False
    validator: str = ""


@dataclass(frozen=True)
class NetworkCheckResult:
    spec: NetworkCheckSpec
    status: NetworkCheckStatus
    message: str
    status_code: int | None = None
    elapsed_ms: int | None = None
    final_url: str = ""
    error: str = ""


ProgressCallback = Callable[[str], None]


def _manager():
    from mdcx.config.manager import manager

    return manager


SPECIAL_CHECK_PATHS: dict[Website, str] = {
    Website.AIRAV_CC: "/playon.aspx?hid=44733",
    Website.JAVDB: "/v/D16Q5?locale=zh",
    Website.JAVBUS: "/FSDSS-660",
    Website.JAVLIBRARY: "/cn/?v=javme2j2tu",
    Website.KIN8: "/moviepages/3681/index.html",
}

DEFAULT_SITE_URLS: dict[Website, str] = {
    Website.DMM: "https://www.dmm.co.jp",
    Website.AVSOX: "https://avsox.click",
    Website.OFFICIAL: "",
}

GROUP_ORDER = ("基础环境", "基础连通性", "刮削站点", "账号/API", "辅助服务")
STATUS_ORDER = {
    NetworkCheckStatus.FAILED: 0,
    NetworkCheckStatus.WARNING: 1,
    NetworkCheckStatus.OK: 2,
    NetworkCheckStatus.SKIPPED: 3,
    NetworkCheckStatus.CANCELLED: 4,
}


def _status_icon(status: NetworkCheckStatus) -> str:
    return {
        NetworkCheckStatus.OK: "✅",
        NetworkCheckStatus.WARNING: "⚠️",
        NetworkCheckStatus.FAILED: "❌",
        NetworkCheckStatus.SKIPPED: "ℹ️",
        NetworkCheckStatus.CANCELLED: "⛔️",
    }[status]


def _elapsed_text(elapsed_ms: int | None) -> str:
    return "-" if elapsed_ms is None else f"{elapsed_ms} ms"


def _status_code_text(status_code: int | None) -> str:
    return "-" if status_code is None else str(status_code)


def _join_url(base_url: str, path: str) -> str:
    if not path:
        return base_url
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _configured_or_default_url(site: Website, default_url: str) -> tuple[str, bool]:
    manager = _manager()
    custom_url = manager.config.get_site_url(site)
    if custom_url:
        return custom_url, True
    return default_url.rstrip("/"), False


def _diagnostic_timeout() -> float:
    manager = _manager()
    return max(min(float(manager.config.timeout or 5), 5.0), 2.0)


def _is_cloudflare_challenge(text: str) -> bool:
    lowered = text.lower()
    challenge_markers = (
        "challenge",
        "ray id",
        "ray-id",
        "cf-browser-verification",
        "just a moment",
        "cf-chl",
        "cdn-cgi/challenge-platform",
        "attention required",
        "enable javascript and cookies",
        "checking your browser before accessing",
    )
    return "cloudflare" in lowered and any(marker in lowered for marker in challenge_markers)


def _is_proxy_error(error: str) -> bool:
    lowered = error.lower()
    return "proxy" in lowered or "socks" in lowered or "tunnel" in lowered


def _message_for_error(error: str) -> str:
    if not error:
        return "请求失败"
    if _is_proxy_error(error):
        return "代理连接失败，请检查代理地址或代理软件"
    if "超时" in error or "timeout" in error.lower():
        return "连接超时，请检查网络或代理节点"
    if "dns" in error.lower() or "resolve" in error.lower():
        return "DNS 解析失败"
    return error


def _clean_error(error: str) -> str:
    error = str(error or "").strip()
    if ": " not in error:
        return error
    left, right = error.split(": ", 1)
    if left.startswith(("GET ", "POST ", "HEAD ")) and right.startswith(left):
        return right
    return error


def _classify_http_result(spec: NetworkCheckSpec, status_code: int, text: str) -> tuple[NetworkCheckStatus, str]:
    if _is_cloudflare_challenge(text):
        return NetworkCheckStatus.WARNING, "被 Cloudflare 挑战页拦截"

    if spec.site == Website.JAVDB:
        manager = _manager()
        if "The owner of this website has banned your access based on your browser's behaving" in text:
            ip_address = re.findall(r"(\d+\.\d+\.\d+\.\d+)", text)
            ip_text = f"{ip_address[0]} " if ip_address else ""
            return NetworkCheckStatus.FAILED, f"当前 IP {ip_text}被 JavDB 封禁"
        if "Due to copyright restrictions" in text or "Access denied" in text:
            return NetworkCheckStatus.FAILED, "当前 IP 被 JavDB 限制，请使用非日本节点"
        if "/logout" in text:
            return NetworkCheckStatus.OK, "连接正常，Cookie 有效"
        if manager.config.javdb:
            return NetworkCheckStatus.WARNING, "站点可访问，但 JavDB Cookie 可能无效"
        return NetworkCheckStatus.OK, "连接正常"

    if spec.site == Website.JAVBUS:
        manager = _manager()
        if "lostpasswd" in text and manager.config.javbus:
            return NetworkCheckStatus.WARNING, "站点可访问，但 JavBus Cookie 可能无效"
        if "lostpasswd" in text:
            return NetworkCheckStatus.WARNING, "当前节点可能需要 JavBus Cookie"
        return NetworkCheckStatus.OK, "连接正常"

    if spec.site == Website.DMM:
        if "このページはお住まいの地域からご利用になれません" in text:
            return NetworkCheckStatus.FAILED, "DMM 地域限制，请使用日本节点"

    if spec.site == Website.MGSTAGE and not text.strip():
        return NetworkCheckStatus.FAILED, "MGStage 返回空页面，通常是地域限制，请使用日本节点"

    if status_code in {401, 403}:
        return NetworkCheckStatus.WARNING, f"HTTP {status_code}，可能需要 Cookie、API Token 或更换节点"
    if status_code == 429:
        return NetworkCheckStatus.WARNING, "HTTP 429，请求被限流"
    if 200 <= status_code < 400:
        return NetworkCheckStatus.OK, "连接正常"
    if 500 <= status_code:
        return NetworkCheckStatus.FAILED, f"站点服务异常 HTTP {status_code}"
    return NetworkCheckStatus.FAILED, f"HTTP {status_code}"


def _is_bypass_capable_client(client: Any) -> bool:
    return callable(getattr(client, "_try_bypass_cloudflare", None))


async def _try_bypass_for_check(
    client: Any,
    spec: NetworkCheckSpec,
) -> tuple[Any | None, str]:
    if not spec.enable_cf_bypass:
        return None, "此检测项未启用 CF Bypass"
    manager = _manager()
    if not manager.config.cf_bypass_url.strip():
        return None, "未配置 CF Bypass"
    if not _is_bypass_capable_client(client):
        return None, "当前客户端不支持 CF Bypass"

    try:
        from httpx import URL
    except Exception as exc:
        return None, f"URL 解析依赖不可用: {exc}"

    try:
        host = URL(spec.url).host or ""
    except Exception as exc:
        return None, f"URL 解析失败: {exc}"
    if not host:
        return None, "URL 缺少 host"

    return await client._try_bypass_cloudflare(
        host=host,
        method=spec.method,
        target_url=spec.url,
        headers=spec.headers or None,
        cookies=spec.cookies or None,
        data=None,
        json_data=None,
        # CF Bypass 往往需要启动浏览器、刷新 Cookie 或等待挑战页完成, 使用 AsyncWebClient 内置的
        # _cf_bypass_timeout, 不用普通诊断请求的短超时覆盖。
        timeout=None,
        allow_redirects=True,
        use_proxy=spec.use_proxy,
    )


def _format_header() -> list[str]:
    manager = _manager()
    use_proxy = bool(manager.config.use_proxy and manager.config.proxy)
    cf_bypass_url = manager.config.cf_bypass_url.strip()
    cf_bypass_proxy = manager.config.cf_bypass_proxy.strip()
    lines = [time.strftime("%Y-%m-%d %H:%M:%S").center(88, "=")]
    lines.append("基础环境")
    lines.append(f"  {'代理状态':<16}{'已启用' if use_proxy else '未启用'}")
    if use_proxy:
        lines.append(f"  {'代理地址':<16}{manager.config.proxy}")
    lines.append(f"  {'CF Bypass':<16}{'已配置' if cf_bypass_url else '未配置'}")
    lines.append(f"  {'CF Bypass代理':<16}{'已配置' if cf_bypass_proxy else '未配置'}")
    lines.append(f"  {'诊断超时':<16}{_diagnostic_timeout():.1f}s")
    lines.append("=" * 88)
    return lines


def format_result_line(result: NetworkCheckResult) -> str:
    icon = _status_icon(result.status)
    name = result.spec.name[:18]
    status_code = _status_code_text(result.status_code)
    elapsed = _elapsed_text(result.elapsed_ms)
    message = result.message
    if result.error and result.status == NetworkCheckStatus.FAILED:
        if result.error not in message:
            message = f"{message}: {result.error}"
    return f"  {icon} {name:<18} {status_code:>4}  {elapsed:>8}  {message}"


def format_summary(results: list[NetworkCheckResult], elapsed: float, cancelled: bool) -> list[str]:
    failed = sum(1 for result in results if result.status == NetworkCheckStatus.FAILED)
    warning = sum(1 for result in results if result.status == NetworkCheckStatus.WARNING)
    ok = sum(1 for result in results if result.status == NetworkCheckStatus.OK)
    skipped = sum(1 for result in results if result.status == NetworkCheckStatus.SKIPPED)
    status = "已取消" if cancelled else "已完成"
    lines = [
        "-" * 88,
        f"网络检测{status}：正常 {ok}，警告 {warning}，失败 {failed}，跳过 {skipped}，用时 {elapsed:.2f} 秒",
    ]
    if failed or warning:
        lines.append("建议优先查看失败/警告项；若基础连通性失败，先检查代理或系统网络。")
    lines.append("=" * 88)
    return lines


async def _build_site_specs() -> list[NetworkCheckSpec]:
    from mdcx.crawlers import get_crawler, get_registered_crawler_sites

    manager = _manager()
    specs: list[NetworkCheckSpec] = []
    for site in get_registered_crawler_sites(include_hidden=False):
        if site == Website.THEPORNDB:
            continue
        crawler_cls = get_crawler(site)
        if crawler_cls is None:
            continue

        default_url = DEFAULT_SITE_URLS.get(site)
        if default_url is None:
            try:
                default_url = crawler_cls.base_url_()
            except Exception:
                default_url = ""

        base_url, customized = _configured_or_default_url(site, default_url or "")
        if not base_url:
            specs.append(
                NetworkCheckSpec(
                    name=site.value,
                    group="刮削站点",
                    url="",
                    site=site,
                    note="没有固定入口，按实际番号动态检测",
                )
            )
            continue

        path = SPECIAL_CHECK_PATHS.get(site, "")
        url = _join_url(base_url, path)
        headers: dict[str, str] = {}
        cookies: dict[str, str] = {}
        use_proxy = True
        if site == Website.JAVDB and manager.config.javdb:
            headers["cookie"] = manager.config.javdb
        elif site == Website.JAVBUS:
            headers["Accept-Language"] = "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6"
            if manager.config.javbus:
                headers["cookie"] = manager.config.javbus
        elif site == Website.JAVLIBRARY and customized:
            use_proxy = False
        elif site == Website.MGSTAGE:
            cookies["adc"] = "1"
        elif site == Website.JAVDBAPI:
            url = f"{url.rstrip('/')}/movies?q=ssni-200"
            specs.append(
                NetworkCheckSpec(
                    name=site.value,
                    group="账号/API",
                    url=url,
                    site=site,
                    headers={"Accept": "application/json"},
                    validator="javdbapi",
                )
            )
            continue
        elif site == Website.GETCHU or site == Website.GETCHU_DMM:
            specs.append(
                NetworkCheckSpec(
                    name=site.value,
                    group="刮削站点",
                    url=url,
                    site=site,
                    use_proxy=use_proxy,
                    encoding="euc-jp",
                )
            )
            continue

        specs.append(
            NetworkCheckSpec(
                name=site.value,
                group="刮削站点",
                url=url,
                site=site,
                use_proxy=use_proxy,
                headers=headers,
                cookies=cookies,
                enable_cf_bypass=True,
            )
        )
    return specs


def _build_static_specs() -> list[NetworkCheckSpec]:
    manager = _manager()
    specs = [
        NetworkCheckSpec(
            name="GitHub Raw",
            group="基础连通性",
            url="https://raw.githubusercontent.com",
            use_proxy=bool(manager.config.use_proxy and manager.config.proxy),
        ),
        NetworkCheckSpec(
            name="通用 HTTPS",
            group="基础连通性",
            url="https://www.google.com/generate_204",
            use_proxy=bool(manager.config.use_proxy and manager.config.proxy),
        ),
    ]

    cf_bypass_url = manager.config.cf_bypass_url.strip()
    if cf_bypass_url:
        health_url = cf_bypass_url.rstrip("/") + "/cookies?url=http://example.com"
        bypass_proxy = manager.config.cf_bypass_proxy.strip()
        if bypass_proxy:
            health_url += "&proxy=" + quote_plus(bypass_proxy)
        specs.append(NetworkCheckSpec(name="CF Bypass", group="辅助服务", url=health_url, use_proxy=False))
    else:
        specs.append(
            NetworkCheckSpec(
                name="CF Bypass",
                group="辅助服务",
                url="",
                note="未配置，仅遇到 Cloudflare 挑战页时需要",
            )
        )

    api_token = manager.config.theporndb_api_token.strip()
    if api_token:
        specs.append(
            NetworkCheckSpec(
                name="ThePornDB Token",
                group="账号/API",
                url="https://api.theporndb.net/scenes/hash/8679fcbdd29fa735",
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                validator="theporndb_token",
            )
        )
    else:
        specs.append(
            NetworkCheckSpec(
                name="ThePornDB Token",
                group="账号/API",
                url="",
                warning_if_missing="未填写 API Token，影响欧美刮削",
            )
        )
    return specs


async def build_network_check_specs() -> list[NetworkCheckSpec]:
    return [*_build_static_specs(), *(await _build_site_specs())]


async def run_network_check_item(
    spec: NetworkCheckSpec,
    *,
    cancel_event: threading.Event | None = None,
    client: "AsyncWebClient | Any | None" = None,
) -> NetworkCheckResult:
    if cancel_event and cancel_event.is_set():
        return NetworkCheckResult(spec=spec, status=NetworkCheckStatus.CANCELLED, message="已取消")
    if spec.warning_if_missing:
        return NetworkCheckResult(spec=spec, status=NetworkCheckStatus.WARNING, message=spec.warning_if_missing)
    if not spec.url:
        return NetworkCheckResult(spec=spec, status=NetworkCheckStatus.SKIPPED, message=spec.note or "无固定检测入口")

    start_time = time.perf_counter()
    try:
        request_client = client or _manager().computed.async_client
        response, error = await request_client.request(
            spec.method,
            spec.url,
            headers=spec.headers or None,
            cookies=spec.cookies or None,
            use_proxy=spec.use_proxy,
            timeout=_diagnostic_timeout(),
            retry_count=1,
            enable_cf_bypass=spec.enable_cf_bypass and bool(_manager().config.cf_bypass_url.strip()),
        )
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        if cancel_event and cancel_event.is_set():
            return NetworkCheckResult(spec=spec, status=NetworkCheckStatus.CANCELLED, message="已取消")
        if response is None:
            clean_error = _clean_error(error)
            message = _message_for_error(clean_error)
            return NetworkCheckResult(
                spec=spec,
                status=NetworkCheckStatus.FAILED,
                message=message,
                elapsed_ms=elapsed_ms,
                error=clean_error,
            )

        text = ""
        try:
            response.encoding = spec.encoding
            text = response.text or ""
        except Exception as exc:
            return NetworkCheckResult(
                spec=spec,
                status=NetworkCheckStatus.WARNING,
                message=f"响应可达，但文本解析失败: {exc}",
                status_code=response.status_code,
                elapsed_ms=elapsed_ms,
                final_url=str(getattr(response, "url", "") or ""),
            )

        if _is_cloudflare_challenge(text) and spec.enable_cf_bypass and _manager().config.cf_bypass_url.strip():
            bypass_response, bypass_error = await _try_bypass_for_check(request_client, spec)
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            if bypass_response is None:
                clean_error = _clean_error(bypass_error)
                return NetworkCheckResult(
                    spec=spec,
                    status=NetworkCheckStatus.FAILED,
                    message="Cloudflare Bypass 失败",
                    status_code=int(response.status_code),
                    elapsed_ms=elapsed_ms,
                    final_url=str(getattr(response, "url", "") or ""),
                    error=clean_error,
                )
            response = bypass_response
            try:
                response.encoding = spec.encoding
                text = response.text or ""
            except Exception as exc:
                return NetworkCheckResult(
                    spec=spec,
                    status=NetworkCheckStatus.WARNING,
                    message=f"Bypass 响应可达，但文本解析失败: {exc}",
                    status_code=response.status_code,
                    elapsed_ms=elapsed_ms,
                    final_url=str(getattr(response, "url", "") or ""),
                )
            if not _is_cloudflare_challenge(text):
                bypass_mode = ""
                try:
                    bypass_mode = response.headers.get("x-mdcx-bypass-mode", "")
                except Exception:
                    bypass_mode = ""
                status, message = _classify_http_result(spec, int(response.status_code), text)
                if status == NetworkCheckStatus.OK:
                    mode_text = f"（{bypass_mode}）" if bypass_mode else ""
                    message = f"连接正常，已通过 CF Bypass{mode_text}"
                return NetworkCheckResult(
                    spec=spec,
                    status=status,
                    message=message,
                    status_code=int(response.status_code),
                    elapsed_ms=elapsed_ms,
                    final_url=str(getattr(response, "url", "") or ""),
                )

        status, message = _classify_http_result(spec, int(response.status_code), text)
        if spec.validator == "theporndb_token":
            status, message = _classify_theporndb_token(int(response.status_code), text)
        elif spec.validator == "javdbapi":
            status, message = _classify_javdbapi(int(response.status_code), text)
        elif spec.name == "CF Bypass" and status == NetworkCheckStatus.OK:
            message = "服务可用"

        return NetworkCheckResult(
            spec=spec,
            status=status,
            message=message,
            status_code=int(response.status_code),
            elapsed_ms=elapsed_ms,
            final_url=str(getattr(response, "url", "") or ""),
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return NetworkCheckResult(
            spec=spec,
            status=NetworkCheckStatus.FAILED,
            message="检测异常",
            elapsed_ms=elapsed_ms,
            error=str(exc),
        )


def _classify_theporndb_token(status_code: int, text: str) -> tuple[NetworkCheckStatus, str]:
    if status_code == 401 and "Unauthenticated" in text:
        return NetworkCheckStatus.FAILED, "API Token 错误"
    if status_code == 200 and '"data"' in text:
        return NetworkCheckStatus.OK, "API Token 有效"
    if status_code == 200:
        return NetworkCheckStatus.WARNING, "API 返回数据异常"
    return _classify_http_result(
        NetworkCheckSpec(name="ThePornDB Token", group="账号/API", url="", site=Website.THEPORNDB), status_code, text
    )


def _classify_javdbapi(status_code: int, text: str) -> tuple[NetworkCheckStatus, str]:
    if status_code == 200 and ("universal_id" in text or "SSNI" in text.upper()):
        return NetworkCheckStatus.OK, "API 查询正常"
    if status_code == 200:
        return NetworkCheckStatus.WARNING, "API 可访问，但 ssni-200 查询返回数据异常"
    return _classify_http_result(
        NetworkCheckSpec(name="javdbapi", group="账号/API", url="", site=Website.JAVDBAPI), status_code, text
    )


async def run_network_check(
    *,
    progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
    concurrency: int = 10,
    client: "AsyncWebClient | Any | None" = None,
    emit_header: bool = True,
) -> list[NetworkCheckResult]:
    progress = progress or (lambda line: None)
    if emit_header:
        for line in _format_header():
            progress(line)

    specs = await build_network_check_specs()
    results: list[NetworkCheckResult] = []
    grouped_specs = {group: [spec for spec in specs if spec.group == group] for group in GROUP_ORDER}
    semaphore = asyncio.Semaphore(max(int(concurrency), 1))

    async def run_one(spec: NetworkCheckSpec) -> NetworkCheckResult:
        async with semaphore:
            return await run_network_check_item(spec, cancel_event=cancel_event, client=client)

    start_time = time.perf_counter()
    for group in GROUP_ORDER:
        group_specs = grouped_specs.get(group, [])
        if not group_specs or group == "基础环境":
            continue
        progress(group)
        tasks = [asyncio.create_task(run_one(spec)) for spec in group_specs]
        for task in asyncio.as_completed(tasks):
            if cancel_event and cancel_event.is_set():
                task.close()
                for pending in tasks:
                    pending.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                elapsed = time.perf_counter() - start_time
                for line in format_summary(results, elapsed, cancelled=True):
                    progress(line)
                return results
            result = await task
            results.append(result)
            progress(format_result_line(result))

    elapsed = time.perf_counter() - start_time
    for line in format_summary(results, elapsed, cancelled=bool(cancel_event and cancel_event.is_set())):
        progress(line)
    return sorted(
        results,
        key=lambda result: (
            GROUP_ORDER.index(result.spec.group) if result.spec.group in GROUP_ORDER else len(GROUP_ORDER),
            STATUS_ORDER[result.status],
            result.spec.name,
        ),
    )
