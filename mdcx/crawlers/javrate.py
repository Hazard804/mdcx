import json
import re
from datetime import date
from typing import override
from urllib.parse import quote, urljoin

from parsel import Selector

from ..config.models import Website
from ..signals import signal
from .base import BaseCrawler, CralwerException, CrawlerData, DetailPageParser, FieldRes

# 站点为繁中页面, 部分标签存在繁简两种写法, 统一按包含匹配以兼容站点改版
NUMBER_LABELS = ("番號", "番号", "编号", "編號")
RELEASE_LABELS = ("發片日期", "发行日期", "發行日期")

# 无码数字番号在站点内使用站族前缀, 本地番号(如 052416_304)直接搜索无法命中.
# 站内写法: 一本道用下划线, 其余站族用短横线; 搜索接口对分隔符敏感, 另一种写法作为兜底候选.
UNCENSORED_PREFIX_PATTERN = re.compile(r"^(\d{6})[-_](\d{2,4})$")
UNCENSORED_SEPARATORS = {"1PON": "_", "CARIB": "-", "10MU": "-", "PACO": "-"}


def normalize_code(value: str) -> str:
    """番号归一化: 仅去除首尾空白并转大写, 保留 - 与 _ 的原始写法."""
    return str(value or "").strip().upper()


def code_matches(candidate: str, number: str) -> bool:
    """
    判断站点返回的番号是否与目标番号对应.

    站点对无码数字番号会带上站族前缀(1PON-052416_304), 因此仅对纯数字番号放宽为后缀匹配;
    普通番号必须完全一致, 避免把 ABC-123 误判为 ABC_123 或 ABC-1234.
    """
    candidate_code = normalize_code(candidate)
    target = normalize_code(number)
    if not candidate_code or not target:
        return False
    if candidate_code == target:
        return True
    if match := UNCENSORED_PREFIX_PATTERN.fullmatch(target):
        head, tail = match.groups()
        return candidate_code.endswith(f"{head}_{tail}") or candidate_code.endswith(f"{head}-{tail}")
    return False


def search_candidates(number: str) -> list[str]:
    """生成搜索关键词候选: 原始番号优先, 无码数字番号再补站族前缀写法."""
    raw_number = str(number or "").strip()
    if not raw_number:
        return []

    candidates = [raw_number]
    if match := UNCENSORED_PREFIX_PATTERN.fullmatch(raw_number):
        head, tail = match.groups()
        # 先试站内实际写法, 命中即停止; 备用写法只在前面全部落空时才会额外请求
        candidates.extend(f"{prefix}-{head}{separator}{tail}" for prefix, separator in UNCENSORED_SEPARATORS.items())
        for prefix, separator in UNCENSORED_SEPARATORS.items():
            alternate = "-" if separator == "_" else "_"
            candidates.append(f"{prefix}-{head}{alternate}{tail}")

    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = normalize_code(candidate)
        if key and key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def parse_release(value: str) -> str:
    """解析发布日期, 仅接受可校验的完整日期, 避免把无效文本当作日期写入."""
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""

    if not (match := re.search(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})", raw_value)):
        return ""
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def parse_iso_duration(value: str) -> str:
    """解析 ld+json 的 ISO 8601 时长(PT2H3M12S), 返回分钟数."""
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    match = re.fullmatch(r"P(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", raw_value, re.IGNORECASE)
    if not match:
        return ""
    hours, minutes, seconds = (int(part) if part else 0 for part in match.groups())
    total_minutes = hours * 60 + minutes
    if total_minutes == 0 and seconds > 0:
        return "1"
    return str(total_minutes) if total_minutes > 0 else ""


def parse_duration_text(value: str) -> str:
    """解析页面上的时长文本(02 : 03 : 12), 返回分钟数."""
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    if not (match := re.fullmatch(r"(\d{1,2})\s*[:：]\s*(\d{2})\s*[:：]\s*(\d{2})", raw_value)):
        return ""
    hours, minutes, seconds = (int(part) for part in match.groups())
    total_minutes = hours * 60 + minutes
    if total_minutes == 0 and seconds > 0:
        return "1"
    return str(total_minutes) if total_minutes > 0 else ""


def parse_score(value: str) -> str:
    """解析评分, 仅保留 0-5 之间的数值."""
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    match = re.search(r"(\d+(?:\.\d+)?)", raw_value)
    if not match:
        return ""
    try:
        score = float(match.group(1))
    except ValueError:
        return ""
    return match.group(1) if 0 < score <= 5 else ""


def mosaic_from_type(value: str) -> str:
    """把站点的类型徽标(有碼A片/無碼A片/國產A片)归一为马赛克类型."""
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    if "無碼" in raw_value or "无码" in raw_value:
        return "无码"
    if "國產" in raw_value or "国产" in raw_value:
        return "国产"
    if "有碼" in raw_value or "有码" in raw_value:
        return "有码"
    return ""


def upgrade_cover_url(url: str) -> str:
    """
    把站点的封面缩略图(_s/_m/_thumbnail)升级为高清大图(_l).

    站点仅对部分封面提供尺寸后缀, 老片封面是无后缀的 jpg, 此时保持原地址不变.
    """
    raw_url = str(url or "").strip()
    if not raw_url.startswith("http"):
        return ""
    base, dot, extension = raw_url.rpartition(".")
    if not dot or extension.lower() not in {"webp", "jpg", "jpeg", "png"}:
        return raw_url
    if not re.search(r"_(?:s|m|l|thumbnail)$", base):
        return raw_url
    return f"{re.sub(r'_(?:s|m|l|thumbnail)$', '', base)}_l.{extension}"


def image_base_key(url: str) -> str:
    """提取图片地址的底图标识, 用于判断两张图是否为同一素材的不同尺寸."""
    raw_url = str(url or "").strip().split("?")[0]
    if not raw_url:
        return ""
    return re.sub(r"_(?:right_)?(?:s|m|l|thumbnail)$", "", raw_url.rpartition(".")[0])


def poster_url_from_cover(url: str) -> str:
    """
    由封面地址推导竖版海报地址(_right_l).

    站点海报与封面位于同一目录:
    - 新片封面在 /compressed/ 目录下, 直接替换后缀即可;
    - 老片封面是无后缀 jpg, 海报统一存放在同日期目录的 /compressed/ 下。
    这里只做地址推导, 是否可用由请求层校验。
    """
    raw_url = str(url or "").strip()
    if not raw_url.startswith("http"):
        return ""
    base, dot, extension = raw_url.rpartition(".")
    if not dot or extension.lower() not in {"webp", "jpg", "jpeg", "png"}:
        return ""
    base = re.sub(r"_(?:s|m|l|thumbnail)$", "", base)
    if "/compressed/" in raw_url:
        return f"{base}_right_l.webp"
    head, separator, name = base.rpartition("/")
    if not separator:
        return ""
    # 老片封面为 https://host/{日期目录}/{文件名}.jpg, 海报位于 https://host/compressed/{日期目录}/ 下
    scheme_host, separator, date_folder = head.rpartition("/")
    if not separator or not date_folder:
        return ""
    return f"{scheme_host}/compressed/{date_folder}/{name}_right_l.webp"


def _clean_list(values: list[str] | None) -> list[str]:
    """去除空值并保序去重."""
    result: list[str] = []
    for value in values or []:
        item = str(value or "").strip()
        if item and item not in result:
            result.append(item)
    return result


def _info_row_texts(html: Selector, labels: tuple[str, ...]) -> list[str]:
    """按 info-label 文案精确取同一 info-row 内的 info-value 文本."""
    if not labels:
        return []
    condition = " or ".join(f"contains(normalize-space(.), '{label}')" for label in labels)
    xpath = (
        f"//span[contains(@class,'info-label') and ({condition})]"
        "/ancestor::div[contains(@class,'info-row')][1]"
        "//span[contains(@class,'info-value')]//text()"
    )
    return [text.strip() for text in html.xpath(xpath).getall() if text.strip()]


def _info_row_text(html: Selector, labels: tuple[str, ...]) -> str:
    return "".join(_info_row_texts(html, labels)).strip()


def _ld_json(html: Selector) -> dict:
    """解析详情页的 ld+json 结构化数据, 失败时返回空字典."""
    text = html.xpath('//script[@type="application/ld+json"]/text()').get(default="")
    if not text:
        return {}
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _looks_like_code(value: str) -> bool:
    """判断文本是否像番号, 避免把标题或说明文字当作番号."""
    raw_value = str(value or "").strip()
    if not raw_value or len(raw_value) > 40 or " " in raw_value:
        return False
    return bool(re.search(r"[0-9A-Za-z]", raw_value))


def _is_cloudflare_challenge(html: str) -> bool:
    """识别 Cloudflare 人机验证页, 避免把验证页误判为「未匹配到番号」."""
    return any(marker in html for marker in ("Just a moment", "__cf_chl_opt", "cf-browser-verification"))


class JavrateParser(DetailPageParser):
    """javrate 详情页解析器. 字段缺失时返回空值, 不做跨字段兜底猜测."""

    def _site_number(self, html: Selector) -> str:
        number = _info_row_text(html, NUMBER_LABELS)
        if not _looks_like_code(number):
            # 信息行缺失时退回标题前的番号, 避免标题里残留番号前缀
            number = html.xpath("normalize-space(//article//h1/strong[1])").get(default="")
        return number.strip() if _looks_like_code(number) else ""

    @override
    async def number(self, ctx, html) -> FieldRes:
        return self._site_number(html)

    @override
    async def title(self, ctx, html) -> FieldRes:
        raw_title = html.xpath("normalize-space(//article//h1)").get(default="").strip()
        if not raw_title:
            return ""
        number = self._site_number(html)
        if number and raw_title.upper().startswith(number.upper()):
            # 只剔除标题开头的番号, 避免误删标题自带的连接符号
            raw_title = raw_title[len(number) :].lstrip(" -~　").strip()
        return raw_title

    @override
    async def originaltitle(self, ctx, html) -> FieldRes:
        return await self.title(ctx, html)

    @override
    async def outline(self, ctx, html) -> FieldRes:
        paragraphs = html.xpath("//div[contains(@class,'description-text')]//p//text()").getall()
        if not paragraphs:
            paragraphs = html.xpath("//div[contains(@class,'description-text')]//text()").getall()
        lines: list[str] = []
        for paragraph in paragraphs:
            line = str(paragraph or "").strip()
            # 首行是站点固定前缀「【在綫觀看】番号」, 不属于简介内容
            if not line or line.startswith("【在綫觀看】"):
                continue
            lines.append(line)
        return "\n".join(lines)

    @override
    async def originalplot(self, ctx, html) -> FieldRes:
        return await self.outline(ctx, html)

    @override
    async def actors(self, ctx, html) -> FieldRes[list[str]]:
        return _clean_list(html.xpath("//a[contains(@class,'actress-swiper-link')]/@data-actress-name").getall())

    @override
    async def all_actors(self, ctx, html) -> FieldRes[list[str]]:
        return await self.actors(ctx, html)

    @override
    async def tags(self, ctx, html) -> FieldRes[list[str]]:
        return _clean_list(html.xpath("//a[contains(@class,'keyword-tag-link')]/@data-keyword-name").getall())

    @override
    async def release(self, ctx, html) -> FieldRes:
        return parse_release(_info_row_text(html, RELEASE_LABELS))

    @override
    async def year(self, ctx, html) -> FieldRes:
        release = parse_release(_info_row_text(html, RELEASE_LABELS))
        return release[:4] if release else ""

    @override
    async def runtime(self, ctx, html) -> FieldRes:
        duration = parse_iso_duration(str(_ld_json(html).get("duration") or ""))
        if duration:
            return duration
        # 结构化数据缺失时回退到详情页顶部的时长徽标
        for text in html.xpath("//article//span[contains(@class,'badge')]//text()").getall():
            if duration := parse_duration_text(text):
                return duration
        return ""

    @override
    async def score(self, ctx, html) -> FieldRes:
        raw_score = "".join(html.xpath("//span[contains(@class,'movie-score-badge')]//text()").getall())
        return parse_score(raw_score)

    @override
    async def studio(self, ctx, html) -> FieldRes:
        values = html.xpath("//a[contains(@class,'issuer-link')]/@data-issuer-name").getall()
        return next((value.strip() for value in values if str(value or "").strip()), "")

    @override
    async def publisher(self, ctx, html) -> FieldRes:
        return await self.studio(ctx, html)

    @override
    async def series(self, ctx, html) -> FieldRes:
        values = html.xpath("//a[contains(@class,'movieset-link')]/@data-movieset-name").getall()
        return next((value.strip() for value in values if str(value or "").strip()), "")

    @override
    async def thumb(self, ctx, html) -> FieldRes:
        cover = html.xpath("//div[contains(@class,'movie-detail-bg')]/img/@src").get(default="")
        return upgrade_cover_url(cover)

    @override
    async def poster(self, ctx, html) -> FieldRes:
        cover = html.xpath("//div[contains(@class,'movie-detail-bg')]/img/@src").get(default="")
        return poster_url_from_cover(cover)

    @override
    async def extrafanart(self, ctx, html) -> FieldRes[list[str]]:
        photos = html.xpath("//a[@data-photo-url]/@data-photo-url").getall()
        return _clean_list([photo for photo in photos if str(photo or "").strip().startswith("http")])

    @override
    async def mosaic(self, ctx, html) -> FieldRes:
        raw_type = html.xpath("normalize-space(//h2[contains(@class,'movie-type-badge')])").get(default="")
        return mosaic_from_type(raw_type)


class JavrateCrawler(BaseCrawler):
    parser = JavrateParser()

    @staticmethod
    def _log(message: str) -> None:
        signal.add_log(f"🎬 [Javrate] {message}")

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVRATE

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.javrate.com"

    @override
    async def _generate_search_url(self, ctx) -> list[str] | str | None:
        candidates = search_candidates(ctx.input.number)
        if not candidates:
            raise CralwerException("番号为空")
        ctx.debug(f"搜索候选: {candidates}")
        return [f"{self.base_url}/search/{quote(candidate)}" for candidate in candidates]

    @override
    async def _search(self, ctx, search_urls: list[str]) -> list[str] | None:
        ok_pages = 0
        challenged = 0
        for search_url in search_urls:
            html, error = await self._fetch_search(ctx, search_url)
            if html is None:
                ctx.debug(f"搜索页请求失败: {error=}")
                continue
            if _is_cloudflare_challenge(html):
                challenged += 1
                ctx.debug(f"搜索页被 Cloudflare 拦截: {search_url=}")
                continue
            ok_pages += 1
            ctx.debug(f"搜索页请求成功: {search_url=}")
            detail_urls = await self._parse_search_page(ctx, Selector(text=html), search_url)
            if detail_urls:
                return detail_urls if isinstance(detail_urls, list) else [detail_urls]

        # 区分「请求失败/被拦截」与「确实没有该番号」, 避免向用户报错误的失败原因
        if ok_pages == 0:
            if challenged:
                raise CralwerException("触发 Cloudflare 验证, 请在【设置】-【网络】-【CF Bypass】配置本地服务")
            raise CralwerException("搜索页请求失败, 请检查网络设置")
        raise CralwerException("搜索结果: 未匹配到番号！")

    @override
    async def _parse_search_page(self, ctx, html: Selector, search_url: str) -> list[str] | str | None:
        for card in html.xpath("//a[@data-movie-code][contains(@href,'/movie/detail/')]"):
            code = card.attrib.get("data-movie-code", "")
            href = card.attrib.get("href", "")
            if not href or not code_matches(code, ctx.input.number):
                continue
            detail_url = urljoin(self.base_url, href)
            ctx.debug(f"命中番号: {code} -> {detail_url}")
            return detail_url
        ctx.debug("搜索结果均为模糊匹配, 已放弃")
        return None

    @override
    async def _parse_detail_page(self, ctx, html: Selector, detail_url: str) -> CrawlerData | None:
        data = await self.parser.parse(ctx, html, external_id=detail_url)
        if not data.title:
            raise CralwerException("数据获取失败: 未获取到标题")
        if not data.number:
            data.number = ctx.input.number
        return data

    @override
    def _get_headers(self, ctx) -> dict[str, str] | None:
        return {"Accept-Language": "zh-TW,zh;q=0.9,zh-CN;q=0.8"}

    async def _check_image_url(self, ctx, url: str) -> bool:
        """
        探测海报地址是否可用.

        站点约一半标题没有竖版海报, 必须先探活再写入结果; 这里复用刮削任务自身的客户端,
        保证与站点请求使用同一代理与指纹配置。
        """
        response, error = await self.async_client.request("HEAD", url)
        if response is None:
            ctx.debug(f"海报探测失败: {url} ({error})")
            return False
        content_type = str(response.headers.get("Content-Type", "")).lower()
        if response.status_code != 200 or not content_type.startswith("image/"):
            ctx.debug(f"海报不是有效图片: {url} ({response.status_code} {content_type})")
            return False
        return True

    async def _resolve_poster(self, ctx, poster: str) -> str:
        """校验推导出的竖版海报地址, 不可用时回退到小尺寸海报, 全部失败则留空走裁剪."""
        candidate = str(poster or "").strip()
        if not candidate:
            return ""
        fallback = candidate.replace("_right_l.webp", "_right_s.webp")
        for url in dict.fromkeys((candidate, fallback)):
            if not url.startswith("http"):
                continue
            if await self._check_image_url(ctx, url):
                if url != candidate:
                    self._log(f"海报大图不可用, 已回退小图: {url}")
                return url
        self._log(f"海报地址校验失败, 改用封面裁剪: {candidate}")
        return ""

    def _clean_extrafanart(self, thumb: str, images: list[str] | None) -> list[str]:
        """剧照去重, 并去掉与封面同底图的副本(站点会把大封面当作剧照返回)."""
        cover_key = image_base_key(thumb)
        result: list[str] = []
        for image in images or []:
            url = str(image or "").strip()
            if not url.startswith("http"):
                continue
            if cover_key and image_base_key(url) == cover_key:
                continue
            if url not in result:
                result.append(url)
        return result

    @override
    async def post_process(self, ctx, res):
        res.thumb = upgrade_cover_url(res.thumb or "")
        res.poster = await self._resolve_poster(ctx, res.poster or "")
        res.image_download = bool(res.poster)
        res.extrafanart = self._clean_extrafanart(res.thumb, res.extrafanart)
        if not res.extrafanart:
            ctx.debug("剧照为空, 已跳过")
        if not res.publisher:
            res.publisher = res.studio
        if res.release and not res.year:
            res.year = res.release[:4]
        return res
