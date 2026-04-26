import time
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from mdcx.config.models import Language, Website
from mdcx.gen.field_enums import CrawlerResultFields
from mdcx.models.log_buffer import LogBuffer
from mdcx.models.types import CrawlerInput, CrawlerResponse, CrawlerResult
from mdcx.utils.dataclass import update

from .types import Context, CralwerException

v1_cralwers = {}


def register_v1_crawler(site: Website, fn: Callable):
    v1_cralwers[site] = LegacyCrawler(fn=fn, site_=site)


def get_v1_crawler(site: Website) -> "LegacyCrawler":
    if site not in v1_cralwers:
        raise CralwerException(f"v1 crawler for {site} not found")
    return v1_cralwers[site]


def _select_language_payload(
    payloads: dict[str, dict],
    language: Language,
    org_language: Language,
) -> dict:
    if not isinstance(payloads, dict):
        return {}

    candidates: list[str] = []
    for lang in (language, org_language):
        if lang != Language.UNDEFINED:
            candidates.append(lang.value)
            if lang == Language.ZH_CN:
                candidates.append(Language.ZH_TW.value)
            elif lang == Language.ZH_TW:
                candidates.append(Language.ZH_CN.value)

    for fallback in (Language.JP.value, Language.ZH_CN.value, Language.ZH_TW.value, ""):
        candidates.append(fallback)

    for key in dict.fromkeys(candidates):
        value = payloads.get(key)
        if isinstance(value, dict):
            return value

    for value in payloads.values():
        if isinstance(value, dict):
            return value

    return {}


@dataclass
class LegacyCrawler:
    fn: Callable[..., Awaitable[dict[str, dict[str, dict]]]]
    site_: Website

    def site(self) -> Website:
        """与 `GenericBaseCrawler.site` 兼容的方法."""
        return self.site_

    def __call__(self, client, base_url, *args, **kwargs) -> "LegacyCrawler":
        return self

    async def close(self): ...

    async def run(self, input: CrawlerInput) -> CrawlerResponse:
        """与 `GenericBaseCrawler.run` 兼容的包装器."""
        start_time = time.time()
        ctx = Context(input=input)
        ctx.debug(f"{input=}")

        try:
            data = await self._run(ctx)
            ctx.debug_info.execution_time = time.time() - start_time
            return CrawlerResponse(data=data, debug_info=ctx.debug_info)
        except Exception:
            ctx.debug(traceback.format_exc())
            return CrawlerResponse(debug_info=ctx.debug_info)

    async def _run(self, ctx: Context) -> CrawlerResult:
        if ctx.input.language == Language.UNDEFINED:
            language = ""
        else:
            language = ctx.input.language.value
        if ctx.input.org_language == Language.UNDEFINED:
            org_language = ""
        else:
            org_language = ctx.input.org_language.value

        r = await self.fn(
            **{
                "number": ctx.input.number,
                "appoint_url": ctx.input.appoint_url,
                "language": language,
                "file_path": str(ctx.input.file_path) if ctx.input.file_path else "",
                "appoint_number": ctx.input.appoint_number,
                "mosaic": ctx.input.mosaic,
                "short_number": ctx.input.short_number,
                "org_language": org_language,
            }
        )

        if info := LogBuffer.info().buffer:
            ctx.debug("v1 crawler info log:")
            ctx.debug_info.logs.extend(info)
        if error := LogBuffer.error().buffer:
            ctx.debug("v1 crawler error log:")
            ctx.debug_info.logs.extend(error)

        res = list(r.values())[0]
        # v1 crawler 一般返回 {site: {language: data}}。
        # 少数来源会在一次请求中返回多语言 dict，这里按请求语言精确取值；
        # 若目标语言不存在，则回退到相近中文或首个可用结果，兼容旧行为。
        res = _select_language_payload(res, ctx.input.language, ctx.input.org_language)
        if not res or "title" not in res or not res["title"]:
            raise CralwerException(f"v1 crawler failed: {self.site_}")

        # 处理字段重命名
        if r := res.get("actor"):
            res[CrawlerResultFields.ACTORS] = to_list(r)
        if r := res.get("all_actor"):
            res[CrawlerResultFields.ALL_ACTORS] = to_list(r)
        if r := res.get("director"):
            res[CrawlerResultFields.DIRECTORS] = to_list(r)
        if r := res.get("tag"):
            res[CrawlerResultFields.TAGS] = to_list(r)
        if r := res.get("website"):
            res[CrawlerResultFields.EXTERNAL_ID] = r

        return update(CrawlerResult.empty(), res)


def to_list(v: str | list[str]) -> list[str]:
    if isinstance(v, str):
        v = v.strip()
        return v.split(",") if v else []
    return v
