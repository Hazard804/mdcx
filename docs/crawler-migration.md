# 刮削器新版框架迁移指南

本文档用于指导将旧版函数式刮削器迁移到 `mdcx.crawlers.base` 新版框架。目标是在不破坏原有行为的前提下，逐步移除旧版 `main()` 入口和 `LegacyCrawler` 注册。

## 目标

- 所有刮削源最终统一为 `GenericBaseCrawler` / `BaseCrawler` 子类。
- 运行时通过 `register_crawler()` 注册新版类，不再依赖 `register_v1_crawler()`。
- 单站点调用统一返回 `CrawlerResponse`，成功数据统一为 `CrawlerResult`。
- 调试信息进入 `CrawlerDebugInfo.logs`，错误进入 `CrawlerDebugInfo.error`。
- 迁移完成的站点应删除旧 `main()` 入口、旧调试样例和不再使用的 `actor_photo` 兼容代码。

## 新版框架边界

新版框架核心文件：

- `mdcx/crawlers/base/base.py`：生命周期、搜索、详情、异常捕获、注册表。
- `mdcx/crawlers/base/types.py`：`Context`、`CrawlerData`、`NOT_SUPPORT`。
- `mdcx/crawlers/base/parser.py`：`DetailPageParser` 和解析 helper。
- `mdcx/crawlers/__init__.py`：新版和旧版注册入口。

标准 HTML 站点优先继承 `BaseCrawler`：

```python
class XxxCrawler(BaseCrawler):
    @classmethod
    def site(cls) -> Website:
        return Website.XXX

    @classmethod
    def base_url_(cls) -> str:
        return "https://example.com"

    async def _generate_search_url(self, ctx):
        return f"{self.base_url}/search?q={ctx.input.number}"

    async def _parse_search_page(self, ctx, html, search_url):
        return ["https://example.com/detail/xxx"]

    async def _parse_detail_page(self, ctx, html, detail_url):
        return CrawlerData(title="...", external_id=detail_url)
```

当站点需要额外状态时，定义自定义 `Context`：

```python
@dataclass
class XxxContext(Context):
    matched_number: str = ""

class XxxCrawler(GenericBaseCrawler[XxxContext]):
    def new_context(self, input: CrawlerInput) -> XxxContext:
        return XxxContext(input=input)
```

当站点不是“搜索页 -> 详情页”模型，例如 API、POST 直接返回详情 HTML、多个接口聚合，可以重写 `_run()`，但仍需返回 `CrawlerResult`，并写入 `debug_info.search_urls/detail_urls`。

## 字段映射规则

旧版字段到新版字段的常见映射：

- `actor` -> `actors: list[str]`
- `all_actor` -> `all_actors: list[str]`
- `director` -> `directors: list[str]`
- `tag` -> `tags: list[str]`
- `website` -> `external_id`
- `source` 不手写，基类会设置为 `site().value`；重写 `_run()` 时需自行设置。

迁移时不要继续生成 `actor_photo`。当前主流程已经不消费旧版返回字典中的该字段。

## 迁移步骤

1. 保留可复用的纯解析 helper，例如 `get_title()`、`get_release()`。
2. 新增 `XxxCrawler`，用 `self.async_client` 替代 `manager.computed.async_client`。
3. 用 `ctx.debug()` 替代旧 `LogBuffer.info()` 调试信息。
4. 用 `CralwerException` 表示站点级失败，让基类统一转为 `CrawlerResponse(debug_info.error=...)`。
5. 在 `mdcx/crawlers/__init__.py` 中新增 `register_crawler(XxxCrawler)`。
6. 从 `CRAWLER_FUNCS` 删除对应旧版注册。
7. 删除旧 `main()`、`if __name__ == "__main__"`、未使用的兼容 helper。
8. 更新或新增测试，优先覆盖纯解析 helper 和新版 `Crawler.run()`。

## 清理标准

一个站点视为迁移完成，需要同时满足：

- 文件内不存在 `async def main(`。
- `mdcx/crawlers/__init__.py` 不再通过 `CRAWLER_FUNCS` 注册该站点。
- 运行时可通过 `get_crawler(site)` 获取新版类。
- 站点内部请求都走 `self.async_client`。
- 不再新增旧版返回字典 `{site: {language: data}}`。
- 不再为新版流程写 `actor_photo`。

## 测试要求

每批迁移至少执行：

```bash
uv run ruff format <changed files>
uv run ruff check <changed files>
uv run pytest tests/crawlers
```

若迁移站点已有独立测试，必须同时执行对应测试文件。若没有测试，至少保证 `tests/crawlers/test_crawler.py` 通过，确认新版类可初始化。

## 分批建议

优先级从低风险到高风险：

1. 常规 HTML 搜索/详情站点：例如 `cableav`、`madouqu`、`mmtv`、`dahlia`、`fantastica`、`avsox`、`cnmdb`。
2. 有 POST、特殊编码、Cookie 或图片校验的站点：例如 `jav321`、`mgstage`、`getchu`。
3. 多语言站点：`airav_cc`、`iqqtv`、`javlibrary`。这类必须保留 `ctx.input.language` 行为。
4. API、组合或委托站点：例如 `official`、`theporndb`、`getchu_dmm`。这类通常需要单独设计 `_run()`。

## 当前已迁移站点

- `dmm`
- `javdb`
- `javdbapi`
- `avbase`
- `missav`
- `faleno`
- `jav321`
- `cableav`
- `madouqu`
- `mmtv`
- `dahlia`
- `fantastica`
- `avsox`
- `cnmdb`
- `hscangku`
- `kin8`
- `love6`
- `lulubar`
- `xcity`
- `giga`
- `avsex`
- `mdtv`
- `mgstage`
- `javday`
- `fc2ppvdb`
- `prestige`
- `fc2club`
- `fc2`
- `fc2hub`
- `javbus`
- `freejavbt`
- `hdouban`
- `iqqtv`
- `airav_cc`
- `getchu`
- `getchu_dmm`
- `mywife`
- `javlibrary`
- `official`
- `theporndb`

## 已下线站点

- `airav`：旧域名 `airav.wiki` 当前不可用，且新域名 `airav.io` 对应 `airav_cc` 页面结构。保留 `airav_cc`，不再注册 `airav` 爬虫。
