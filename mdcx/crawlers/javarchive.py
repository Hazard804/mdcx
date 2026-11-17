#!/usr/bin/env python3
"""javarchive.com 爬虫.

站点结构:
- 搜索: GET /search?q={番号}[&page={页码}], 每页 20 条, 按相关度排序; 站点是模糊匹配,
  任意字符串都会返回近似结果, 因此必须自行完成番号精确校验
- 详情: GET /{post_id}-{slug}-pn.html, 路径含日文与方括号, 请求前需对路径做百分号编码
- 详情页骨架: div.first_des(标题) -> div.fisrst_sc(可能是竖版海报, 也可能是随机剧照)
  -> div.Recipepod(itemprop=name 标题 / itemprop=image 横版封面 / 点赞区)
  -> ul#lightgallery(剧照) -> 裸文本信息块
- 信息块没有独立容器, 是 div.news 的直接子文本, 以 <br class="a5555"> 分行. 站点混用多套模板:
  日文制表符(発売日/収録時間/監督/メーカー/レーベル/シリーズ)、中文冒号(出演者/制作/发行商/类型)、
  FC2(标签/卖家/日期/时长)、中文视频站(【影片名称】/【出演女优】/【是否有码】), 因此统一解析成
  字段名->值 的字典后再按白名单取值
- 同一番号常有多篇(不同清晰度、字幕、降码、泄漏版本), 按版本偏好选主版本, 其余版本只用于补齐
  主版本的空字段, 标题与封面不跨版本混用
- 英文字幕版([ENGSUB]/English Sub)整篇使用英文模板, 标题与标签都会是英文, 自动搜索时直接跳过;
  只有用户用 appoint_url 明确指定时才解析
- 站点不提供简介/想看/预告片, 详情页的 ratingValue 实际是点赞数, 这些字段一律不采信
"""

import html
import re
from typing import override
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from parsel import Selector

from ..config.manager import manager
from ..config.models import Website
from .base import (
    BaseCrawler,
    CralwerException,
    CrawlerData,
    DetailPageParser,
    FieldRes,
    is_valid,
)

BASE_URL = "https://javarchive.com"
SEARCH_PATH = "/search"
# 搜索按相关度排序, 精确命中基本都在第 1 页; 命中不足时最多再翻 2 页
MAX_SEARCH_PAGES = 3
# 搜索页保留的候选上限(只为拿到同番号的不同版本, 不一定会抓)
MAX_SEARCH_CANDIDATES = 4
# 常规补抓上限(含主版本)
MAX_DETAIL_FETCHES = 3

# 英文字幕版: 整篇英文模板, 标题/标签都会是英文, 自动搜索时跳过
SUBTITLE_VERSION_RE = re.compile(r"eng[\s_-]*sub|english[\s_-]*(?:sub|subtitles?)", re.IGNORECASE)

# 详情页路由: /{post_id}-{slug}-pn.html, slug 中可能带 "/"
DETAIL_PATH_RE = re.compile(r"^/(?P<post_id>\d+)-.*-pn\.html$", re.IGNORECASE)
# DMM / javstore 的竖版海报与横版封面后缀
POSTER_SUFFIX_RE = re.compile(r"pl\.(?:jpg|jpeg|png|webp)$", re.IGNORECASE)
THUMB_SUFFIX_RE = re.compile(r"ps\.(jpg|jpeg|png|webp)$", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})")
CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
MINUTES_RE = re.compile(r"(\d+)\s*分")
HOURS_RE = re.compile(r"(\d+)\s*(?:時間|时间|小时)")
PRICE_TAG_RE = re.compile(r"^\d+(?:\.\d+)?\s*(?:pt|円|off)$", re.IGNORECASE)
# 品番字段可能是 DMM 内容 ID(如 1start00669), 只有 "字母-数字" 形态才当作番号
NUMBER_SHAPE_RE = re.compile(r"^[0-9A-Z]+[-_][0-9]+$")
PLACEHOLDER_RE = re.compile(r"^(?:-{2,}|TODO|TBD|N/?A|unknown|不明|なし|无|無|未定)$", re.IGNORECASE)
# 占位符也可能是破折号(如 シリーズ —–), 全由横线组成时同样视为缺失
DASH_ONLY_RE = re.compile(r"^[-\u2010-\u2015\u30fc\uff0d\s]+$")
# 信息块字段白名单: 老帖用空格分隔(公開日 2016-08-16), 需要按已知字段名切开
INFO_LABELS = (
    "発売日",
    "商品発売日",
    "配信開始日",
    "公開日",
    "収録時間",
    "監督",
    "メーカー",
    "レーベル",
    "シリーズ",
    "シリーズ名",
    "出演者",
    "出演",
    "女優名",
    "メーカー品番",
    "MGS品番",
    "FANZA品番",
    "品番",
    "タイトル",
    "名称",
    "制作",
    "发行商",
    "發行商",
    "类型",
    "類型",
    "标签",
    "標籤",
    "タグキーワード",
    "女優タイプ",
    "評価",
    "卖家",
    "日期",
    "时长",
    # 英文模板: 自动搜索不抓字幕版, 这里保留解析是为了 appoint_url 直指英文页时仍能取到数据
    "Release Date",
    "Director",
    "Actress",
    "Actor",
    "Tags",
    "Runtime",
    "Series",
    "Maker",
    "Publisher",
    "Studio",
    "Label",
)  # fmt: skip
INFO_LABEL_RE = re.compile(
    "^(?P<label>"
    + "|".join(re.escape(label) for label in sorted(INFO_LABELS, key=len, reverse=True))
    + r")\s*(?P<value>.+)$"
)
# 版本前缀里的修饰词, 出现在番号之后时也要剥离
VERSION_WORD_RE = re.compile(
    r"^(?:reducing[ -]?mosaic|uncensored\s+leaked|chin[ae]s+e\s+sub|chinese\s+sub|eng\s*sub)\s+", re.IGNORECASE
)
# 清晰度类标签属于版本信息, 不作为影片标签写入
TAG_FORMAT_SKIP = {"4K", "2K", "FHD", "HD", "SD", "ハイビジョン", "高画質", "フルハイビジョン"}

# 站内其它镜像域名, 与自定义域名一起构成允许抓取的 host 白名单
DEFAULT_HOSTS = {"javarchive.com", "www.javarchive.com"}


def clean_text(value: str | None) -> str:
    """反转义 HTML 实体、去掉零宽字符并压缩空白."""
    text = html.unescape(value or "")
    text = re.sub(r"[\u200b-\u200f\u2060\ufeff\u00ad]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def split_info_line(line: str) -> tuple[str, str]:
    """把信息块的一行拆成 (字段名, 值).

    兼容四种写法: 制表符(日文模板)、全角冒号(中文模板)、【影片名称】xxx(无分隔符),
    以及空格分隔的老帖(公開日 2016-08-16 / 女優タイプ熟女 美脚).
    """
    for separator in ("\t", "：", ":"):
        label, found, value = line.partition(separator)
        if found:
            return clean_text(label), clean_text(value)
    match = INFO_LABEL_RE.match(line)
    if match:
        return clean_text(match["label"]), clean_text(match["value"])
    # 中文视频站模板没有分隔符, 字段名本身带书名号
    match = re.match(r"^(【[^】]{1,10}】)\s*(.*)$", line)
    if match:
        return clean_text(match.group(1)), clean_text(match.group(2))
    return "", ""


def parse_info_map(html: Selector) -> dict[str, str]:
    """把详情页信息块解析成 {字段名: 值}, 同名字段只保留第一次出现的值."""
    info: dict[str, str] = {}
    # 信息块是 div.news 的直接子文本节点, 每个字段一个文本节点, 不需要再按 <br> 切分
    lines = html.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' news ')]/text()").getall()
    for raw in lines:
        line = raw.replace("\r", "").replace("\n", " ").strip()
        if not line:
            continue
        label, value = split_info_line(line)
        if not label or label in info:
            continue
        info[label] = value
    return info


def is_placeholder(value: str) -> bool:
    """占位符(`----`/`TODO`/`—–`)一律视为缺失, 避免把占位符当成真实字段值."""
    return bool(value) and bool(PLACEHOLDER_RE.match(value) or DASH_ONLY_RE.match(value))


def field_value(info: dict[str, str], *labels: str) -> str:
    """按顺序取第一个非占位符的字段值."""
    for label in labels:
        value = info.get(label, "")
        if not value or is_placeholder(value):
            continue
        return value
    return ""


def parse_date(value: str) -> str:
    """校验并归一化日期, 非法值直接丢弃, 避免写入错误日期."""
    match = DATE_RE.search(value or "")
    if not match:
        return ""
    year, month, day = (int(item) for item in match.groups())
    if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_runtime(value: str) -> str:
    """'120 分' / '2時間3分' / '01:09:38' -> 分钟数, 无有效数字返回空."""
    text = clean_text(value)
    if not text:
        return ""
    clock = CLOCK_RE.fullmatch(text)
    if clock:
        first, second, third = clock.groups()
        if third is None:
            # "57:01" 是 分:秒
            total = int(first) + (1 if int(second) >= 30 else 0)
        else:
            # 与其它站点的 ISO 时长解析保持一致, 秒数满 30 进位
            total = int(first) * 60 + int(second) + (1 if int(third) >= 30 else 0)
        return str(total) if total > 0 else ""
    hours = HOURS_RE.search(text)
    minutes = MINUTES_RE.search(text)
    if hours or minutes:
        total = (int(hours.group(1)) if hours else 0) * 60 + (int(minutes.group(1)) if minutes else 0)
        return str(total) if total > 0 else ""
    numbers = re.findall(r"\d+", text)
    return numbers[0] if numbers else ""


def split_multi(value: str) -> list[str]:
    """按站点使用的多种分隔符拆分多值字段并保序去重."""
    items = (clean_text(item) for item in re.split(r"[｜|,，、/]", value or ""))
    return list(dict.fromkeys(item for item in items if item))


def parse_actors(info: dict[str, str]) -> list[str]:
    """演员只取显式字段, 不在标题里猜测, 避免把片名里的词误判成人名."""
    value = field_value(info, "出演者", "出演", "女優名", "女优名", "【出演女优】", "Actress")
    if not value or value in {"无名", "無名", "不明"}:
        return []
    return split_multi(value)


def parse_all_actors(info: dict[str, str]) -> list[str]:
    """全部演员 = 女优 + 男优(英文模板的 Actor 是男优)."""
    names = parse_actors(info)
    for name in split_multi(field_value(info, "Actor")):
        if name not in names:
            names.append(name)
    return names


def split_tags(value: str) -> list[str]:
    """拆分标签: 多值分隔符优先; 老帖用空格分隔(タグキーワード 手コキ 足コキ)."""
    items = split_multi(value)
    if len(items) == 1 and " " in items[0]:
        items = [item for item in items[0].split(" ") if item]
    return items


def parse_tags(info: dict[str, str]) -> list[str]:
    """标签取 类型/标签/タグキーワード/Tags(英文版), 过滤价格标记与清晰度标记."""
    tags: list[str] = []
    for item in split_tags(field_value(info, "类型", "标签", "標籤", "タグキーワード", "Tags")):
        if PRICE_TAG_RE.fullmatch(item) or item.upper() in TAG_FORMAT_SKIP:
            continue
        tags.append(item)
    return tags


def page_title(html: Selector) -> str:
    """取详情页标题, first_des 为主, itemprop=name 兜底."""
    for expression in ("string(//div[contains(@class,'first_des')])", "string(//span[@itemprop='name'])"):
        value = clean_text(html.xpath(expression).get(default=""))
        if value:
            return value
    return ""


def exact_number_match(title: str, number: str) -> re.Match[str] | None:
    """按原样(保留分隔符)匹配番号."""
    text = clean_text(title)
    target = clean_text(number).upper()
    if not text or not target:
        return None
    return re.compile(rf"(?<![0-9A-Z]){re.escape(target)}(?![0-9A-Z])", re.IGNORECASE).search(text)


def number_pattern(number: str) -> re.Pattern[str] | None:
    """把番号拆成字母数字块, 允许块间出现分隔符差异(如 FC2-PPV-5006586 / FC2PPV 5006586)."""
    chunks = re.findall(r"[0-9A-Z]+", (number or "").upper())
    if not chunks:
        return None
    body = r"[-_ ]*".join(re.escape(chunk) for chunk in chunks)
    return re.compile(rf"(?<![0-9A-Z]){body}(?![0-9A-Z])", re.IGNORECASE)


def match_number(title: str, number: str) -> re.Match[str] | None:
    """先精确匹配, 再退化为忽略分隔符匹配; 前后不允许紧邻字母数字, 避免 SNOS-416 命中 SNOS-4160."""
    exact = exact_number_match(title, number)
    if exact:
        return exact
    pattern = number_pattern(number)
    return pattern.search(clean_text(title)) if pattern else None


def version_rank(title: str, match: re.Match[str] | None) -> int:
    """番号之前的前缀越"素"越好: 裸标题 > 清晰度 > 降码 > 字幕 > 无码泄漏."""
    text = clean_text(title)
    prefix = (text[: match.start()] if match else text[:40]).lower()
    if "uncensored" in prefix or "leak" in prefix:
        return 4
    if "sub" in prefix:
        return 3
    if "reducing" in prefix or "mosaic" in prefix:
        return 2
    if any(word in prefix for word in ("fhd", "4k", "sd", "kbps", "]")):
        return 1
    return 0


def is_subtitle_version(title: str, url: str = "") -> bool:
    """是否为英文字幕版. 标题与 URL slug 任一命中都算, URL 里的方括号可能已被编码."""
    return bool(SUBTITLE_VERSION_RE.search(clean_text(title)) or SUBTITLE_VERSION_RE.search(unquote(url or "")))


def clean_title(title: str, number: str) -> str:
    """去掉版本前缀与番号, 只保留片名; 以番号匹配位置切分, 避免误删片名里的短横线."""
    text = clean_text(title)
    if not text:
        return ""
    match = match_number(text, number)
    if not match:
        return text
    rest = text[match.end() :].lstrip(" -_/|:：·・")
    rest = VERSION_WORD_RE.sub("", rest).strip()
    return rest or text


def normalize_image_url(url: str) -> str:
    """站点部分老图地址带空格(如 HEYZO 1234.jpg), 直接请求会被判为非法 URL."""
    return clean_text(url).replace(" ", "%20")


def parse_thumb(html: Selector) -> str:
    """横版封面: itemprop=image(DMM 的 ps.jpg 或 javstore 图)."""
    return normalize_image_url(html.xpath("string(//img[@itemprop='image']/@src)").get(default=""))


def derive_poster(thumb: str) -> str:
    """同一内容的竖版海报与横版封面同路径, 仅结尾 ps/pl 不同."""
    match = THUMB_SUFFIX_RE.search(thumb or "")
    if not match:
        return ""
    return thumb[: match.start()] + "pl." + match.group(1)


def parse_poster(html: Selector, thumb: str) -> str:
    """竖版海报: fisrst_sc 里的图不一定是海报(实测有随机剧照), 只认 pl.* 结尾的图."""
    for url in html.xpath("//div[contains(@class,'fisrst_sc')]//img/@src").getall():
        url = normalize_image_url(url)
        if POSTER_SUFFIX_RE.search(url):
            return url
    return derive_poster(thumb)


def parse_gallery(html: Selector) -> list[str]:
    """剧照: lightgallery 的 data-src 大图, 保序去重."""
    urls = [normalize_image_url(url) for url in html.xpath("//ul[@id='lightgallery']/li/@data-src").getall()]
    return list(dict.fromkeys(url for url in urls if url))


class JavarchiveParser(DetailPageParser):
    @override
    async def number(self, ctx, html) -> FieldRes:
        target = clean_text(ctx.input.number)
        if target and match_number(page_title(html), target):
            return target
        # 标题里没有番号时退到品番类字段, 过滤掉 DMM 内容 ID
        info = parse_info_map(html)
        for label in ("メーカー品番", "MGS品番", "品番"):
            value = field_value(info, label).upper()
            if value and NUMBER_SHAPE_RE.fullmatch(value):
                return value
        return target

    @override
    async def title(self, ctx, html) -> FieldRes:
        return clean_title(page_title(html), clean_text(ctx.input.number))

    @override
    async def originaltitle(self, ctx, html) -> FieldRes:
        # 部分模板(中文冒号)会单独给出日文原名, 优先使用
        original = field_value(parse_info_map(html), "タイトル", "名称", "【影片名称】")
        if original:
            return clean_title(original, clean_text(ctx.input.number))
        return await self.title(ctx, html)

    @override
    async def actors(self, ctx, html) -> FieldRes[list[str]]:
        return parse_actors(parse_info_map(html))

    @override
    async def all_actors(self, ctx, html) -> FieldRes[list[str]]:
        return parse_all_actors(parse_info_map(html))

    @override
    async def directors(self, ctx, html) -> FieldRes[list[str]]:
        return split_multi(field_value(parse_info_map(html), "監督", "监督", "Director"))

    @override
    async def tags(self, ctx, html) -> FieldRes[list[str]]:
        return parse_tags(parse_info_map(html))

    @override
    async def release(self, ctx, html) -> FieldRes:
        # 只用发行类字段, 不拿列表页/文章发布日兜底, 也不使用早于发售日的 配信開始日
        info = parse_info_map(html)
        for label in ("発売日", "商品発売日", "公開日", "Release Date", "日期"):
            release = parse_date(field_value(info, label))
            if release:
                return release
        return ""

    @override
    async def year(self, ctx, html) -> FieldRes:
        release = await self.release(ctx, html)
        return release[:4] if isinstance(release, str) and release else ""

    @override
    async def runtime(self, ctx, html) -> FieldRes:
        return parse_runtime(field_value(parse_info_map(html), "収録時間", "时长", "Runtime"))

    @override
    async def studio(self, ctx, html) -> FieldRes:
        # 卖家 是 FC2 模板里对应的制作方; 英文模板只用 Maker, 不用 Studio(见下方说明)
        return field_value(parse_info_map(html), "メーカー", "制作", "卖家", "Maker")

    @override
    async def publisher(self, ctx, html) -> FieldRes:
        # レーベル 缺失时留空, 不用 メーカー 顶替, 否则发行商会被写成制作商.
        # 英文模板的 Studio 在多数片商处等于 メーカー(如 MOODYZ/IDEA POCKET), 但 S1 的
        # Studio 给的是 レーベル(S1 NO.1 STYLE), 语义不稳定, 因此 Studio/Label 一律不映射.
        return field_value(parse_info_map(html), "レーベル", "发行商", "Publisher")

    @override
    async def series(self, ctx, html) -> FieldRes:
        # 只有 シリーズ 才是系列, レーベル 不是
        return field_value(parse_info_map(html), "シリーズ", "Series")

    @override
    async def thumb(self, ctx, html) -> FieldRes:
        return parse_thumb(html)

    @override
    async def poster(self, ctx, html) -> FieldRes:
        return parse_poster(html, parse_thumb(html))

    @override
    async def extrafanart(self, ctx, html) -> FieldRes[list[str]]:
        return parse_gallery(html)

    @override
    async def image_download(self, ctx, html) -> bool:
        # 有竖版海报才直下, 否则交给后续用横版封面裁剪
        return bool(parse_poster(html, parse_thumb(html)))


class JavarchiveCrawler(BaseCrawler):
    parser = JavarchiveParser()

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVARCHIVE

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.JAVARCHIVE, BASE_URL)

    def _allowed_hosts(self) -> set[str]:
        """允许抓取的 host: 默认站点域名 + 用户自定义域名."""
        hosts = set(DEFAULT_HOSTS)
        host = (urlsplit(self.base_url).hostname or "").lower()
        if host:
            hosts.add(host)
        return hosts

    def _detail_url(self, url: str) -> str:
        """把站内链接归一成详情页绝对地址, 非详情页返回空."""
        absolute = urljoin(f"{self.base_url}/", clean_text(url))
        parts = urlsplit(absolute)
        if (parts.hostname or "").lower() not in self._allowed_hosts():
            return ""
        if not DETAIL_PATH_RE.match(parts.path):
            return ""
        return absolute

    @staticmethod
    def _encode_url(url: str) -> str:
        """路径含日文与方括号, 部分客户端会判为非法 URL, 统一做百分号编码."""
        parts = urlsplit(url)
        path = quote(unquote(parts.path), safe="/")
        return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))

    @override
    async def _generate_search_url(self, ctx) -> list[str] | str | None:
        number = clean_text(ctx.input.number)
        if not number:
            raise CralwerException("番号为空")
        return f"{self.base_url}{SEARCH_PATH}?q={quote(number)}"

    @override
    async def _search(self, ctx, search_urls: list[str]) -> list[str] | None:
        last_error = ""
        for search_url in search_urls:
            candidates: list[str] = []
            for page in range(1, MAX_SEARCH_PAGES + 1):
                page_url = search_url if page == 1 else f"{search_url}&page={page}"
                page_html, error = await self._fetch_search(ctx, page_url)
                if page_html is None:
                    last_error = error
                    ctx.debug(f"搜索页请求失败: {page_url=} {error=}")
                    break
                page_urls = await self._parse_search_page(ctx, Selector(text=page_html), page_url)
                if page_urls is None:
                    # 0 条结果, 后续页必然为空
                    ctx.debug(f"搜索页无任何结果: {page_url=}")
                    break
                if page_urls:
                    # 同番号的各个版本会聚在同一页, 首页已有精确命中就不再翻页
                    candidates = list(dict.fromkeys([*candidates, *page_urls]))
                    ctx.debug(f"搜索页命中 {len(page_urls)} 条: {page_url=}")
                    break
            if candidates:
                return candidates[:MAX_SEARCH_CANDIDATES]
        if last_error:
            raise CralwerException(f"搜索页请求失败: {last_error}")
        raise CralwerException("搜索结果: 未匹配到番号！")

    @override
    async def _parse_search_page(self, ctx, html: Selector, search_url: str) -> list[str] | None:
        target = clean_text(ctx.input.number)
        if not target:
            return None
        cards = html.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' news_1n ')]"
            "[.//h2/a[normalize-space(.)='Search Results']]//li/a[@title]"
        )
        if not cards:
            return None

        # 版本偏好优先, 其次分隔符完全一致, 最后保持站点原始顺序
        scored: list[tuple[int, int, int, str]] = []
        for order, card in enumerate(cards):
            card_title = clean_text(card.attrib.get("title", ""))
            detail_url = self._detail_url(card.attrib.get("href", ""))
            if not card_title or not detail_url:
                continue
            match = match_number(card_title, target)
            if not match:
                continue
            if is_subtitle_version(card_title, detail_url):
                # 字幕版通篇英文, 抓进来会把英文标题/英文标签写进库
                ctx.debug(f"跳过英文字幕版: {card_title[:40]}")
                continue
            exact = 0 if exact_number_match(card_title, target) else 1
            scored.append((version_rank(card_title, match), exact, order, detail_url))
        if not scored:
            ctx.debug(f"无可用候选(均为模糊匹配或英文字幕版), 已放弃: {ctx.input.number}")
            return []
        scored.sort()
        detail_urls = list(dict.fromkeys(item[3] for item in scored))
        ctx.debug(f"精确命中 {len(detail_urls)} 条: {detail_urls[:MAX_SEARCH_CANDIDATES]}")
        return detail_urls

    @override
    async def _fetch_detail(self, ctx, url: str, use_browser: bool | None = False) -> tuple[str | None, str]:
        detail_url = self._detail_url(url)
        if not detail_url:
            return None, "非 javarchive 详情页地址"
        return await self._fetch(ctx, self._encode_url(detail_url), use_browser)

    @override
    async def _parse_detail_page(self, ctx, html: Selector, detail_url: str) -> CrawlerData | None:
        if not html.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' news ')]"):
            page_name = clean_text(html.xpath("string(//title)").get(default=""))
            if "just a moment" in page_name.lower():
                raise CralwerException("站点风控拦截, 请稍后重试")
            raise CralwerException("数据获取失败: 未找到影片信息区块")
        if not page_title(html):
            raise CralwerException("数据获取失败: 未获取到标题")
        data = await self.parser.parse(ctx, html, external_id=detail_url)
        if not data.number:
            data.number = clean_text(ctx.input.number)
        ctx.debug(f"详情页解析完成: {detail_url=} {data.number=} {data.release=} {data.runtime=}")
        return data

    MERGE_FIELDS = (
        "directors",
        "actors",
        "all_actors",
        "tags",
        "release",
        "year",
        "runtime",
        "studio",
        "publisher",
        "series",
    )

    # 常规补齐只看这几项: 日文模板本身不提供演员/标签, 为它们多抓版本通常补不出来
    REQUIRED_FIELDS = ("release", "year", "runtime", "directors", "studio", "publisher")

    @classmethod
    def _fill_missing_fields(cls, ctx, target: CrawlerData, source: CrawlerData, source_url: str) -> None:
        """同番号的其它版本只用于补齐主版本的空字段, 已有值一律不覆盖."""
        for field_name in cls.MERGE_FIELDS:
            if is_valid(getattr(target, field_name)):
                continue
            value = getattr(source, field_name)
            if not is_valid(value):
                continue
            setattr(target, field_name, value)
            ctx.debug(f"补齐字段: {field_name} <- {source_url}")

    @classmethod
    def _has_missing_fields(cls, data: CrawlerData) -> bool:
        return any(not is_valid(getattr(data, field_name)) for field_name in cls.REQUIRED_FIELDS)

    async def _fetch_detail_data(self, ctx, detail_url: str) -> tuple[CrawlerData | None, CralwerException | None]:
        """抓取并解析一个详情页, 失败时返回错误而不抛出."""
        page_html, error = await self._fetch_detail(ctx, detail_url)
        if page_html is None:
            ctx.debug(f"详情页请求失败: {detail_url=} {error=}")
            return None, CralwerException(f"详情页请求失败: {error}")
        ctx.debug(f"详情页请求成功: {detail_url=}")
        try:
            data = await self._parse_detail_page(ctx, Selector(text=page_html), detail_url)
        except CralwerException as exc:
            ctx.debug(f"详情页解析失败: {detail_url=} {exc}")
            return None, exc
        if data is not None and not data.external_id:
            data.external_id = detail_url
        return data, None

    @override
    async def _detail(self, ctx, detail_urls: list[str]) -> CrawlerData | None:
        """主版本优先, 关键字段仍有空缺时才继续抓同番号的其它版本补空."""
        merged: CrawlerData | None = None
        last_error: CralwerException | None = None
        for detail_url in detail_urls[:MAX_DETAIL_FETCHES]:
            data, error = await self._fetch_detail_data(ctx, detail_url)
            if error is not None:
                last_error = error
                continue
            if data is None:
                continue
            if merged is None:
                merged = data
            else:
                self._fill_missing_fields(ctx, merged, data, detail_url)
            if not self._has_missing_fields(merged):
                break
        if merged is None and last_error is not None:
            raise last_error
        return merged
