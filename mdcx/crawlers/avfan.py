#!/usr/bin/env python3
"""avfan.com 爬虫.

站点结构:
- 搜索: GET /zh-CN/search?q={关键词}, 结果卡片指向 /zh-CN/movies/{id}, 番号在卡片
  strong.history-link 或封面图 alt 的首段
- 详情: GET /zh-CN/movies/{id}, 常规字段集中在 dl.movie-info, 结构化数据在 ld+json(VideoObject)
- 图片: covers(封面) 与 samples(剧照) 均在 c1.avfan.com, 匿名可下载; 站点只有横版封面,
  无竖版海报, 由后续裁剪生成
- 匿名仅能访问有码内容, FC2 / 无码的详情页会 302 到 /zh-CN/sign_in
"""

import json
import re
from typing import override
from urllib.parse import quote, urljoin, urlparse

from parsel import Selector

from ..config.models import Website
from ..models.types import CrawlerResult
from .base import BaseCrawler, CralwerException, CrawlerData, DetailPageParser, FieldRes

BASE_URL = "https://avfan.com"
# 固定使用简体中文站点, 详情页的字段标签才能稳定匹配
LANG_PREFIX = "/zh-CN"
MOVIE_URL_PREFIX = f"{LANG_PREFIX}/movies/"

# 详情页路由可能带其它语言前缀, 统一改写为简体中文, 保证 dl.movie-info 的字段名可匹配
MOVIE_URL_RE = re.compile(
    r"^(?P<scheme>https?)://(?P<host>[^/]+)/(?:[a-zA-Z-]{2,5}/)?movies/(?P<movie_id>[^/?#]+)", re.IGNORECASE
)

# 站点标签链接携带内容类型: censored=有码, uncensored=无码, western=欧美
MOSAIC_BY_TAG_TYPE = {"censored": "有码", "uncensored": "无码", "western": "欧美"}


def parse_json_ld(html: Selector) -> dict:
    """合并页面内所有 ld+json, 返回首个 VideoObject, 解析失败时返回空字典."""
    for raw in html.xpath('//script[@type="application/ld+json"]/text()').getall():
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            types = item.get("@type")
            types = types if isinstance(types, list) else [types]
            if "VideoObject" in types:
                return item
    return {}


def info_value(html: Selector, *labels: str) -> str:
    """按 dl.movie-info 里的字段名取值, 取不到返回空字符串."""
    for label in labels:
        # 标签文本可能在 dt 的直接文本节点里, 也可能被包在子节点中, 两种写法都要兼容
        dd = html.xpath(
            f"//dt[normalize-space(text())='{label}' or normalize-space(.)='{label}']/following-sibling::dd[1]"
        )
        if not dd:
            continue
        value = dd.xpath("string()").get(default="")
        value = re.sub(r"\s+", " ", value).strip(" ,")
        if value:
            return value
    return ""


def parse_runtime(value: str) -> str:
    """'120 分钟' / '2 小时 3 分钟' -> 分钟数, 无有效数字返回空."""
    text = re.sub(r"\s+", " ", value or "").strip()
    if not text:
        return ""
    hours = re.search(r"(\d+)\s*(?:小时|小時|时间|時間)", text)
    minutes = re.search(r"(\d+)\s*(?:分钟|分鐘|分)", text)
    if hours or minutes:
        total = (int(hours.group(1)) if hours else 0) * 60 + (int(minutes.group(1)) if minutes else 0)
        return str(total) if total > 0 else ""
    numbers = re.findall(r"\d+", text)
    return numbers[0] if numbers else ""


def parse_iso_duration(value: str) -> str:
    """ISO8601 时长 'PT2H3M12S' / 'PT120M' -> 分钟数, 非法值返回空."""
    match = re.fullmatch(r"P(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", (value or "").strip().upper())
    if not match:
        return ""
    hours, minutes, seconds = (int(item) if item else 0 for item in match.groups())
    total = hours * 60 + minutes + (1 if seconds >= 30 else 0)
    return str(total) if total > 0 else ""


def parse_release(value: str) -> str:
    """校验日期格式, 非法值直接丢弃, 避免写入错误日期."""
    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value or "")
    if not match:
        return ""
    year, month, day = (int(item) for item in match.groups())
    if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_score(value: str) -> str:
    """解析 '3.92分, 由383人评分' 或结构化数据里的 '3.9', 仅接受 0-5."""
    text = (value or "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)\s*分", text) or re.fullmatch(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return ""
    raw = match.group(1)
    try:
        score = float(raw)
    except ValueError:
        return ""
    return raw if 0 < score <= 5 else ""


def parse_wanted(value: str) -> str:
    """解析 '1215人想看' 中的人数."""
    match = re.search(r"([\d,]+)\s*(?:人想看|人想睇|want to watch)", value or "", re.I)
    return match.group(1).replace(",", "") if match else ""


def parse_mosaic(html: Selector) -> str:
    """从标签链接的 t 参数判断内容类型, 无标签时留空避免误判."""
    for href in html.xpath("//a[contains(@class,'tag-chip')]/@href").getall():
        match = re.search(r"[?&]t=(censored|uncensored|western)", href or "")
        if match:
            return MOSAIC_BY_TAG_TYPE.get(match.group(1), "")
    return ""


def parse_gallery(html: Selector) -> tuple[str, list[str]]:
    """返回 (封面, 剧照列表). 页面 gallery 第一项为预告片入口, 其后是封面与 sample 大图."""
    covers = [url for url in html.xpath("//a[@data-fancybox='gallery']/@href").getall() if "/covers/" in url]
    samples = [url for url in html.xpath("//a[@data-fancybox='gallery']/@href").getall() if "/samples/" in url]
    cover = covers[0] if covers else ""
    # 剧照使用 l_N 大图, 去掉与封面重复的项并保序
    images = list(dict.fromkeys(url for url in samples if url and url != cover))
    return cover, images


def actor_names(html: Selector, with_male: bool) -> list[str]:
    """按页面顺序取演员名, 站点用 female/male 标记性别."""
    condition = "contains(@class,'female') or contains(@class,'male')" if with_male else "contains(@class,'female')"
    names: list[str] = []
    for node in html.xpath(f"//dl[contains(@class,'movie-info')]//a[{condition}]"):
        name = node.xpath("string()").get(default="").strip()
        if name and name not in names:
            names.append(name)
    return names


def normalize_number(value: str) -> str:
    """归一化番号用于精确比对, 仅忽略大小写与分隔符差异."""
    return re.sub(r"[^0-9A-Z]", "", (value or "").upper())


def card_number(card: Selector) -> str:
    """取搜索结果卡片上的番号, 依次尝试 strong.history-link、封面 alt、链接 title."""
    strong = card.xpath(".//strong[contains(@class,'history-link')]/text()").get(default="").strip()
    if strong:
        return strong
    alt = card.xpath(".//img/@alt").get(default="").strip()
    if alt:
        return alt.split(" ", 1)[0].strip()
    title = card.xpath("./@title").get(default="").strip()
    match = re.match(r"\[([^\]]+)\]", title)
    return (match.group(1) if match else title.split(" ", 1)[0]).strip()


def movie_url(url: str) -> str:
    """把任意语言前缀的详情页 URL 改写为简体中文路由, 非详情页 URL 返回空."""
    match = MOVIE_URL_RE.match(url or "")
    if not match:
        return ""
    return f"{match.group('scheme').lower()}://{match.group('host').lower()}{MOVIE_URL_PREFIX}{match.group('movie_id')}"


class AvfanParser(DetailPageParser):
    @override
    async def number(self, ctx, html) -> FieldRes:
        value = html.xpath("string(//span[contains(@class,'movie-number')])").get(default="")
        return re.sub(r"\s+", "", value)

    @override
    async def title(self, ctx, html) -> FieldRes:
        # h1 内还会放一个「[原标题]」切换链接, 取文本节点可避开该链接
        parts = [text.strip() for text in html.xpath("//h1/text()").getall() if text.strip()]
        if parts:
            return " ".join(parts)
        # 兜底使用 og:title, 并去掉前缀番号
        fallback = html.xpath("string(//meta[@property='og:title']/@content)").get(default="").strip()
        number = await self.number(ctx, html)
        if isinstance(number, str) and number and fallback.upper().startswith(number.upper()):
            fallback = fallback[len(number) :].lstrip(" -_")
        return fallback

    @override
    async def originaltitle(self, ctx, html) -> FieldRes:
        origin = html.xpath("//*[@data-origin-title]/@data-origin-title").get(default="").strip()
        return origin or await self.title(ctx, html)

    @override
    async def outline(self, ctx, html) -> FieldRes:
        return str(parse_json_ld(html).get("description") or "").strip()

    @override
    async def originalplot(self, ctx, html) -> FieldRes:
        return await self.outline(ctx, html)

    @override
    async def actors(self, ctx, html) -> FieldRes[list[str]]:
        return actor_names(html, with_male=False)

    @override
    async def all_actors(self, ctx, html) -> FieldRes[list[str]]:
        return actor_names(html, with_male=True)

    @override
    async def directors(self, ctx, html) -> FieldRes[list[str]]:
        value = info_value(html, "导演", "監督", "Director")
        return [item.strip() for item in re.split(r"[,，、/]", value) if item.strip()]

    @override
    async def tags(self, ctx, html) -> FieldRes[list[str]]:
        tags = html.xpath("//dl[contains(@class,'movie-info')]//a[contains(@class,'tag-chip')]")
        return list(
            dict.fromkeys(tag.strip() for tag in (a.xpath("string()").get(default="") for a in tags) if tag.strip())
        )

    @override
    async def release(self, ctx, html) -> FieldRes:
        # 发行日期缺失时回退到结构化数据的 uploadDate
        release = parse_release(info_value(html, "发行日期", "發行日期", "Release Date"))
        return release or parse_release(str(parse_json_ld(html).get("uploadDate") or ""))

    @override
    async def year(self, ctx, html) -> FieldRes:
        release = await self.release(ctx, html)
        return release[:4] if release else ""

    @override
    async def runtime(self, ctx, html) -> FieldRes:
        runtime = parse_runtime(info_value(html, "片长", "片長", "Duration"))
        return runtime or parse_iso_duration(str(parse_json_ld(html).get("duration") or ""))

    @override
    async def score(self, ctx, html) -> FieldRes:
        # 页面评分保留两位小数, 优先取可见文本; 取不到再用结构化数据
        visible = html.xpath("string(//*[contains(text(),'人评分')])").get(default="")
        score = parse_score(visible)
        if score:
            return score
        rating = parse_json_ld(html).get("aggregateRating") or {}
        if isinstance(rating, dict) and rating.get("ratingValue"):
            return parse_score(str(rating.get("ratingValue")))
        return ""

    @override
    async def wanted(self, ctx, html) -> FieldRes:
        texts = html.xpath("//*[contains(text(),'人想看') or contains(text(),'人想睇')]/text()").getall()
        return parse_wanted(" ".join(texts))

    @override
    async def series(self, ctx, html) -> FieldRes:
        return info_value(html, "系列", "系列名", "Series")

    @override
    async def studio(self, ctx, html) -> FieldRes:
        return info_value(html, "制作商", "製作商", "Maker")

    @override
    async def publisher(self, ctx, html) -> FieldRes:
        return info_value(html, "发行商", "發行商", "Publisher")

    @override
    async def thumb(self, ctx, html) -> FieldRes:
        cover, _ = parse_gallery(html)
        if cover:
            return cover
        return str(
            parse_json_ld(html).get("thumbnailUrl")
            or html.xpath("string(//meta[@property='og:image']/@content)").get(default="")
        ).strip()

    @override
    async def poster(self, ctx, html) -> FieldRes:
        # 站点只有横版封面, 竖版海报交由后续裁剪生成
        return ""

    @override
    async def extrafanart(self, ctx, html) -> FieldRes[list[str]]:
        _, images = parse_gallery(html)
        return images

    @override
    async def trailer(self, ctx, html) -> FieldRes:
        return str(parse_json_ld(html).get("contentUrl") or "").strip()

    @override
    async def mosaic(self, ctx, html) -> FieldRes:
        return parse_mosaic(html)


class AvfanCrawler(BaseCrawler):
    parser = AvfanParser()

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.AVFAN

    @classmethod
    @override
    def base_url_(cls) -> str:
        return BASE_URL

    @override
    async def _generate_search_url(self, ctx) -> list[str] | str | None:
        number = str(ctx.input.number or "").strip()
        if not number:
            raise CralwerException("番号为空")
        return f"{self.base_url}{LANG_PREFIX}/search?q={quote(number)}"

    @override
    async def _search(self, ctx, search_urls: list[str]) -> list[str] | None:
        last_error = ""
        for search_url in search_urls:
            html, error = await self._fetch_search(ctx, search_url)
            if html is None:
                last_error = error
                ctx.debug(f"搜索页请求失败: {error=}")
                continue
            ctx.debug(f"搜索页请求成功: {search_url=}")
            detail_urls = await self._parse_search_page(ctx, Selector(text=html), search_url)
            if detail_urls:
                return detail_urls if isinstance(detail_urls, list) else [detail_urls]
        if last_error:
            raise CralwerException(f"搜索页请求失败: {last_error}")
        raise CralwerException("搜索结果: 未匹配到番号！")

    @override
    async def _parse_search_page(self, ctx, html: Selector, search_url: str) -> list[str] | str | None:
        target = str(ctx.input.number or "").strip().upper()
        target_normalized = normalize_number(target)
        if not target_normalized:
            return None

        cards: list[tuple[str, str]] = []
        host = (urlparse(self.base_url).hostname or "").lower()
        for card in html.xpath("//a[contains(@href,'/movies/')]"):
            target_url = urljoin(self.base_url, card.attrib.get("href", ""))
            # 跳过广告位等站外链接, 只处理本站详情页
            if (urlparse(target_url).hostname or "").lower() != host:
                continue
            detail_url = movie_url(target_url)
            if not detail_url:
                continue
            cards.append((detail_url, card_number(card).strip().upper()))

        # 站点搜索存在模糊匹配: 先要求番号完全一致, 再退化为忽略分隔符比对
        for detail_url, candidate in cards:
            if candidate == target:
                ctx.debug(f"命中番号: {candidate} -> {detail_url}")
                return detail_url
        for detail_url, candidate in cards:
            if normalize_number(candidate) == target_normalized:
                ctx.debug(f"命中番号(忽略分隔符): {candidate} -> {detail_url}")
                return detail_url
        ctx.debug(f"搜索结果均为模糊匹配, 已放弃: {ctx.input.number}")
        return None

    @override
    async def _fetch_detail(self, ctx, url: str, use_browser: bool | None = False) -> tuple[str | None, str]:
        # 用户可能直接粘贴 /ja/movies/xxx 等其它语言路由, 统一改写为简体中文
        return await self._fetch(ctx, movie_url(url) or url, use_browser)

    @override
    async def _parse_detail_page(self, ctx, html: Selector, detail_url: str) -> CrawlerData | None:
        if not html.xpath("//dl[contains(@class,'movie-info')]"):
            # 未登录访问 FC2 / 无码内容会 302 到登录页; 正常页面也可能带登录弹窗, 因此仅在缺信息区块时判定
            page_title = html.xpath("string(//title)").get(default="")
            is_login_page = bool(
                html.xpath("//form[contains(@action,'sessions')]")
                or html.xpath("//input[@type='password']")
                or any(key in page_title for key in ("登录", "登入", "Sign in", "Sign In"))
            )
            if is_login_page:
                raise CralwerException("该内容需要登录后查看, 暂不支持匿名刮削")
            raise CralwerException("数据获取失败: 未找到影片信息区块")
        data = await self.parser.parse(ctx, html, external_id=movie_url(detail_url) or detail_url)
        if not data.title:
            raise CralwerException("数据获取失败: 未获取到标题")
        if not data.number:
            data.number = ctx.input.number
        return data

    @override
    def _get_headers(self, ctx) -> dict[str, str] | None:
        return {"Accept-Language": "zh-CN,zh;q=0.9"}

    @override
    async def post_process(self, ctx, res: CrawlerResult) -> CrawlerResult:
        if not res.publisher:
            res.publisher = res.studio
        # 站点无竖版海报, 统一走封面裁剪
        res.image_download = False
        return res
