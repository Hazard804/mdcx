import sys
import threading
from types import SimpleNamespace

import pytest

from mdcx.config.enums import Website
from mdcx.core.network_check import (
    NetworkCheckSpec,
    NetworkCheckStatus,
    build_network_check_specs,
    format_result_line,
    run_network_check,
    run_network_check_item,
)


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok", url: str = "https://example.test"):
        self.status_code = status_code
        self.text = text
        self.url = url
        self.headers = {}
        self.encoding = "utf-8"


class FakeClient:
    def __init__(self, *, fail_url_part: str = ""):
        self.fail_url_part = fail_url_part
        self.calls: list[dict] = []

    async def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.fail_url_part and self.fail_url_part in url:
            raise RuntimeError("boom")
        return FakeResponse(url=url), ""


class FakeBypassClient:
    def __init__(self, *, bypass_ok: bool = True):
        self.bypass_ok = bypass_ok
        self.calls: list[dict] = []
        self.bypass_calls: list[dict] = []

    async def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return FakeResponse(
            text="<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/x'></script>Cloudflare</html>",
            url=url,
        ), ""

    async def _try_bypass_cloudflare(self, **kwargs):
        self.bypass_calls.append(kwargs)
        if not self.bypass_ok:
            return None, "bypass failed"
        response = FakeResponse(text="<html>ok</html>", url=kwargs["target_url"])
        response.headers["x-mdcx-bypass-mode"] = "mirror"
        return response, ""


class FakeConfig:
    use_proxy = False
    proxy = ""
    cf_bypass_url = ""
    cf_bypass_proxy = ""
    timeout = 5
    javdb = ""
    javbus = ""
    theporndb_api_token = ""

    def get_site_url(self, site, default=""):
        return default


class FakeManager:
    config = FakeConfig()
    computed = None


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fake_manager(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: FakeManager())


@pytest.mark.anyio
async def test_build_network_check_specs_uses_registered_sites_without_key_error(monkeypatch: pytest.MonkeyPatch):
    class DynamicCrawler:
        @classmethod
        def base_url_(cls):
            return ""

    class CustomConfig(FakeConfig):
        def get_site_url(self, site, default=""):
            return "https://custom.example"

    class CustomManager:
        config = CustomConfig()
        computed = None

    fake_crawlers = SimpleNamespace(
        get_registered_crawler_sites=lambda include_hidden=False: [Website.OFFICIAL],
        get_crawler=lambda site: DynamicCrawler,
    )
    monkeypatch.setitem(sys.modules, "mdcx.crawlers", fake_crawlers)
    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: CustomManager())

    specs = await build_network_check_specs()

    assert any(spec.site == Website.OFFICIAL and spec.url == "https://custom.example" for spec in specs)


@pytest.mark.anyio
async def test_run_network_check_item_catches_single_item_exception():
    spec = NetworkCheckSpec(name="bad", group="刮削站点", url="https://bad.example")

    result = await run_network_check_item(spec, client=FakeClient(fail_url_part="bad"))

    assert result.status == NetworkCheckStatus.FAILED
    assert result.message == "检测异常"
    assert result.error == "boom"


@pytest.mark.anyio
async def test_run_network_check_does_not_stop_on_single_item_exception(monkeypatch: pytest.MonkeyPatch):
    async def fake_specs():
        return [
            NetworkCheckSpec(name="good", group="基础连通性", url="https://good.example"),
            NetworkCheckSpec(name="bad", group="基础连通性", url="https://bad.example"),
        ]

    monkeypatch.setattr("mdcx.core.network_check.build_network_check_specs", fake_specs)
    lines: list[str] = []

    results = await run_network_check(
        progress=lines.append, client=FakeClient(fail_url_part="bad"), concurrency=2, emit_header=False
    )

    assert len(results) == 2
    assert {result.spec.name: result.status for result in results} == {
        "good": NetworkCheckStatus.OK,
        "bad": NetworkCheckStatus.FAILED,
    }
    assert any("网络检测已完成" in line for line in lines)


@pytest.mark.anyio
async def test_run_network_check_can_cancel_between_groups(monkeypatch: pytest.MonkeyPatch):
    async def fake_specs():
        return [
            NetworkCheckSpec(name="first", group="基础连通性", url="https://first.example"),
            NetworkCheckSpec(name="second", group="刮削站点", url="https://second.example"),
        ]

    monkeypatch.setattr("mdcx.core.network_check.build_network_check_specs", fake_specs)
    cancel_event = threading.Event()
    lines: list[str] = []

    def progress(line: str):
        lines.append(line)
        if "first" in line:
            cancel_event.set()

    results = await run_network_check(
        progress=progress, cancel_event=cancel_event, client=FakeClient(), concurrency=1, emit_header=False
    )

    assert [result.spec.name for result in results] == ["first"]
    assert any("网络检测已取消" in line for line in lines)


@pytest.mark.anyio
async def test_javdbapi_spec_uses_real_query_url(monkeypatch: pytest.MonkeyPatch):
    class ApiCrawler:
        @classmethod
        def base_url_(cls):
            return "https://api.thejavdb.net/v1"

    fake_crawlers = SimpleNamespace(
        get_registered_crawler_sites=lambda include_hidden=False: [Website.JAVDBAPI],
        get_crawler=lambda site: ApiCrawler,
    )
    monkeypatch.setitem(sys.modules, "mdcx.crawlers", fake_crawlers)

    specs = await build_network_check_specs()

    javdbapi = next(spec for spec in specs if spec.site == Website.JAVDBAPI)
    assert javdbapi.url == "https://api.thejavdb.net/v1/movies?q=ssni-200"
    assert javdbapi.validator == "javdbapi"


def test_format_result_line_does_not_duplicate_error():
    spec = NetworkCheckSpec(name="site", group="刮削站点", url="https://example.test")
    from mdcx.core.network_check import NetworkCheckResult

    result = NetworkCheckResult(
        spec=spec,
        status=NetworkCheckStatus.FAILED,
        message="GET https://example.test 失败: HTTP 403",
        error="GET https://example.test 失败: HTTP 403",
    )

    line = format_result_line(result)

    assert line.count("GET https://example.test 失败: HTTP 403") == 1


@pytest.mark.anyio
async def test_run_network_check_item_actively_uses_cf_bypass_on_challenge(monkeypatch: pytest.MonkeyPatch):
    class BypassConfig(FakeConfig):
        cf_bypass_url = "http://0.0.0.0:8000"

    class BypassManager:
        config = BypassConfig()
        computed = None

    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: BypassManager())
    client = FakeBypassClient()
    spec = NetworkCheckSpec(
        name="cf-site",
        group="刮削站点",
        url="https://cf.example",
        enable_cf_bypass=True,
        headers={"cookie": "a=b"},
    )

    result = await run_network_check_item(spec, client=client)

    assert result.status == NetworkCheckStatus.OK
    assert result.message == "连接正常，已通过 CF Bypass（mirror）"
    assert client.bypass_calls[0]["target_url"] == "https://cf.example"
    assert client.bypass_calls[0]["headers"] == {"cookie": "a=b"}
    assert client.bypass_calls[0]["timeout"] is None


@pytest.mark.anyio
async def test_run_network_check_item_reports_cf_bypass_failure(monkeypatch: pytest.MonkeyPatch):
    class BypassConfig(FakeConfig):
        cf_bypass_url = "http://0.0.0.0:8000"

    class BypassManager:
        config = BypassConfig()
        computed = None

    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: BypassManager())
    spec = NetworkCheckSpec(
        name="cf-site",
        group="刮削站点",
        url="https://cf.example",
        enable_cf_bypass=True,
    )

    result = await run_network_check_item(spec, client=FakeBypassClient(bypass_ok=False))

    assert result.status == NetworkCheckStatus.FAILED
    assert result.message == "Cloudflare Bypass 失败"
    assert result.error == "bypass failed"
