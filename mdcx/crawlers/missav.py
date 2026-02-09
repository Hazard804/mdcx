import re
from typing import override
from urllib.parse import quote, urljoin, urlparse

from parsel import Selector

from ..config.models import Website
from ..number import get_file_number, is_uncensored
from ..signals import signal
from .base import BaseCrawler, CralwerException, CrawlerData, DetailPageParser, extract_all_texts, extract_text


class Parser(DetailPageParser):
    CODE_LABELS = {"番號", "番号", "code"}
    TITLE_LABELS = {"標題", "标题", "title"}
    ACTRESS_LABELS = {"女優", "女优", "actress"}
    ACTOR_LABELS = {"男優", "男优", "actor"}
    NEUTRAL_ACTOR_LABELS = {"演員", "演员", "cast", "performer", "performers"}
    RELEASE_LABELS = {"發行日期", "发行日期", "release date", "releasedate"}
    DURATION_LABELS = {"時長", "时长", "duration", "runtime"}
    TAG_LABELS = {"類型", "类型", "genre", "genres", "tags"}
    TAG_FALLBACK_LABELS = {"標籤", "标签"}
    SERIES_LABELS = {"系列", "series"}
    MAKER_LABELS = {"發行商", "发行商", "maker", "publisher", "studio"}
    DIRECTOR_LABELS = {"導演", "导演", "director"}

    @staticmethod
    def _normalize_label(label: str) -> str:
        label = re.sub(r"[:：\s]+", "", label or "")
        return label.strip().lower()

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        return list(dict.fromkeys([item for item in items if item]))

    @staticmethod
    def _split_names(value: str) -> list[str]:
        if not value:
            return []
        return [
            name.strip()
            for name in re.split(r"[|｜,，/／、]", value)
            if name and name.strip() and name.strip() not in {"-", "_"}
        ]

    @staticmethod
    def _prefer_japanese_name(value: str) -> str:
        name = (value or "").strip()
        if not name:
            return ""
        if match := re.search(r"[（(]\s*([^()（）]+?)\s*[）)]", name):
            jp_name = match.group(1).strip()
            if jp_name:
                return jp_name
        return name

    @classmethod
    def _normalize_person_names(cls, names: list[str]) -> list[str]:
        return cls._dedupe([cls._prefer_japanese_name(name) for name in names if name and name.strip()])

    @classmethod
    def _iter_info_rows(cls, html: Selector):
        rows = html.xpath("//div[contains(@class,'text-secondary')][span]")
        for row in rows:
            label = cls._normalize_label(extract_text(row, "string(span[1])"))
            if not label:
                continue
            value = extract_text(row, "string(span[@class='font-medium'])", "string(time)")
            links = [item.strip() for item in row.xpath(".//a/text()").getall() if item and item.strip()]
            if not value and links:
                value = " | ".join(links)
            yield label, value, links

    @classmethod
    def _find_info_value(cls, html: Selector, labels: set[str]) -> tuple[str, list[str]]:
        normalized_labels = {cls._normalize_label(label) for label in labels}
        for label, value, links in cls._iter_info_rows(html):
            if label in normalized_labels:
                return value, links
        return "", []

    @classmethod
    def _find_info_values(cls, html: Selector, labels: set[str]) -> list[tuple[str, list[str]]]:
        normalized_labels = {cls._normalize_label(label) for label in labels}
        values: list[tuple[str, list[str]]] = []
        for label, value, links in cls._iter_info_rows(html):
            if label in normalized_labels:
                values.append((value, links))
        return values

    @classmethod
    def _extract_names_by_labels(cls, html: Selector, labels: set[str]) -> list[str]:
        value, links = cls._find_info_value(html, labels)
        names = links if links else cls._split_names(value)
        return cls._normalize_person_names(names)

    @staticmethod
    def _extract_og_actors(html: Selector) -> list[str]:
        return [
            name.strip()
            for name in extract_all_texts(html, "//meta[@property='og:video:actor']/@content")
            if name.strip()
        ]

    @staticmethod
    def _to_minutes(duration_raw: str) -> str:
        value = (duration_raw or "").strip()
        if not value:
            return ""
        if not (match := re.search(r"\d+", value)):
            return value

        num = int(match.group())
        if num >= 300:
            return str(max(1, round(num / 60)))
        return str(num)

    @staticmethod
    def _normalize_outline_for_compare(value: str) -> str:
        return re.sub(r"\s+", "", (value or "")).replace("\u3000", "").lower()

    @classmethod
    def _is_site_generic_outline(cls, value: str) -> bool:
        normalized = cls._normalize_outline_for_compare(value)
        if not normalized:
            return True

        markers = [
            "免費高清日本av在線看",
            "免费高清日本av在线看",
            "無需下載",
            "无需下载",
            "開始播放後不會再有廣告",
            "开始播放后不会再有广告",
            "支援任何裝置包括手機",
            "支持任何装置包括手机",
            "可以番號",
            "可以番号",
            "加入會員後可任意收藏影片供日後觀賞",
            "加入会员后可任意收藏影片供日后观赏",
        ]
        hit_count = sum(1 for marker in markers if marker in normalized)
        return hit_count >= 2

    async def number(self, ctx, html: Selector) -> str:
        value, _ = self._find_info_value(html, self.CODE_LABELS)
        return value or ctx.input.number

    async def title(self, ctx, html: Selector) -> str:
        value, _ = self._find_info_value(html, self.TITLE_LABELS)
        if value:
            return value
        return extract_text(html, "//meta[@property='og:title']/@content", "normalize-space(//h1)")

    async def originaltitle(self, ctx, html: Selector) -> str:
        value, _ = self._find_info_value(html, self.TITLE_LABELS)
        return value or await self.title(ctx, html)

    async def actors(self, ctx, html: Selector) -> list[str]:
        actress_names = self._extract_names_by_labels(html, self.ACTRESS_LABELS)
        if actress_names:
            return actress_names

        neutral_names = self._extract_names_by_labels(html, self.NEUTRAL_ACTOR_LABELS)
        if neutral_names:
            return neutral_names

        male_names = self._extract_names_by_labels(html, self.ACTOR_LABELS)
        if male_names:
            return []

        return self._normalize_person_names(self._extract_og_actors(html))

    async def all_actors(self, ctx, html: Selector) -> list[str]:
        actress_names = self._extract_names_by_labels(html, self.ACTRESS_LABELS)
        male_names = self._extract_names_by_labels(html, self.ACTOR_LABELS)
        neutral_names = self._extract_names_by_labels(html, self.NEUTRAL_ACTOR_LABELS)
        all_names = actress_names + male_names + neutral_names
        if not all_names:
            all_names = self._normalize_person_names(self._extract_og_actors(html))
        return self._dedupe(all_names)

    async def directors(self, ctx, html: Selector) -> list[str]:
        value, links = self._find_info_value(html, self.DIRECTOR_LABELS)
        result = links if links else self._split_names(value)
        if not result:
            result = extract_all_texts(html, "//meta[@property='og:video:director']/@content")
        return self._dedupe(result)

    async def outline(self, ctx, html: Selector) -> str:
        outline = extract_text(
            html, "//meta[@property='og:description']/@content", "//meta[@name='description']/@content"
        )
        outline = (outline or "").strip()
        if self._is_site_generic_outline(outline):
            return ""
        return outline

    async def originalplot(self, ctx, html: Selector) -> str:
        return await self.outline(ctx, html)

    async def release(self, ctx, html: Selector) -> str:
        value, _ = self._find_info_value(html, self.RELEASE_LABELS)
        return value or extract_text(html, "//meta[@property='og:video:release_date']/@content")

    async def year(self, ctx, html: Selector) -> str:
        release = await self.release(ctx, html)
        if match := re.search(r"\d{4}", release):
            return match.group()
        return ""

    async def runtime(self, ctx, html: Selector) -> str:
        value, _ = self._find_info_value(html, self.DURATION_LABELS)
        if value:
            return self._to_minutes(value)
        og_duration = extract_text(html, "//meta[@property='og:video:duration']/@content")
        return self._to_minutes(og_duration)

    async def tags(self, ctx, html: Selector) -> list[str]:
        value, links = self._find_info_value(html, self.TAG_LABELS)
        tags = links if links else self._split_names(value)

        if not tags:
            fallback_tags: list[str] = []
            for fb_value, fb_links in self._find_info_values(html, self.TAG_FALLBACK_LABELS):
                fallback_tags.extend(fb_links if fb_links else self._split_names(fb_value))
            tags = fallback_tags

        if not tags:
            tags = extract_all_texts(
                html, "//div[contains(@class,'text-secondary')][span]//a[contains(@href,'/genres/')]/text()"
            )
        return self._dedupe([tag.strip() for tag in tags if tag.strip()])

    async def series(self, ctx, html: Selector) -> str:
        value, links = self._find_info_value(html, self.SERIES_LABELS)
        if links:
            return links[0]
        return value

    async def studio(self, ctx, html: Selector) -> str:
        return ""

    async def publisher(self, ctx, html: Selector) -> str:
        value, links = self._find_info_value(html, self.MAKER_LABELS)
        if links:
            return links[0]
        return value

    async def thumb(self, ctx, html: Selector) -> str:
        return extract_text(html, "//meta[@property='og:image']/@content")

    async def poster(self, ctx, html: Selector) -> str:
        return await self.thumb(ctx, html)

    async def trailer(self, ctx, html: Selector) -> str:
        return ""


class MissavCrawler(BaseCrawler):
    parser = Parser()

    CODE_PATTERN = re.compile(r"(?i)([a-z]{2,10})[-_ ]?(\d{2,6})")
    UNCENSORED_DATE_PATTERN = re.compile(r"^\d{6}[-_]\d{3,4}$")
    URL_LANG_SUFFIXES = {"cn", "en", "jp", "ja", "tw", "hk"}

    SEARCH_BLACKLIST_PREFIXES = {
        "search",
        "genres",
        "genre",
        "makers",
        "maker",
        "actresses",
        "actress",
        "actors",
        "actor",
        "directors",
        "director",
        "series",
        "tags",
        "tag",
        "label",
        "labels",
        "studio",
        "studios",
        "faq",
        "privacy",
        "terms",
        "about",
        "contact",
        "login",
        "register",
        "assets",
        "api",
        "cdn-cgi",
    }
    SOFT_404_TITLE_MARKERS = {
        "missav | 免費高清av在線看",
        "missav | 免费高清av在线看",
        "missav | free jav online streaming",
        "missav | 無料エロ動画見放題",
    }
    SOFT_404_TEXT_MARKERS = {
        "找不到頁面",
        "找不到页面",
        "page not found",
        "not found",
    }

    @staticmethod
    def _log(message: str) -> None:
        signal.add_log(f"🌐 [MISSAV] {message}")

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.MISSAV

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://missav.ws"

    @staticmethod
    def _normalize_keyword(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (value or "").lower())

    @classmethod
    def _parse_code_parts(cls, value: str) -> tuple[str, str] | None:
        if not value:
            return None
        normalized = str(value).strip().lower().replace("_", "-").replace(" ", "")
        match = cls.CODE_PATTERN.search(normalized)
        if not match:
            return None
        prefix = match.group(1).lower()
        digits = match.group(2)
        return prefix, digits

    @classmethod
    def _normalize_digits_for_number(cls, digits: str) -> str:
        digits_no_zero = digits.lstrip("0") or "0"
        if len(digits_no_zero) < 3 and len(digits) >= 3:
            return digits_no_zero.zfill(3)
        return digits_no_zero

    @classmethod
    def _extract_detail_path_parts(cls, url: str) -> list[str]:
        path_parts = [part for part in urlparse(url).path.split("/") if part]
        while path_parts and path_parts[-1].lower() in cls.URL_LANG_SUFFIXES:
            path_parts.pop()
        return path_parts

    @classmethod
    def _extract_slug(cls, url: str) -> str:
        path_parts = cls._extract_detail_path_parts(url)
        if not path_parts:
            return ""
        return path_parts[-1]

    @classmethod
    def _ensure_cn_detail_url(cls, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return url

        path_parts = cls._extract_detail_path_parts(url)
        if not path_parts:
            return url

        path = "/" + "/".join(path_parts + ["cn"])
        return parsed._replace(path=path, params="", query="", fragment="").geturl()

    @staticmethod
    def _normalize_number_case(number: str) -> str:
        number = (number or "").strip()
        if not number:
            return ""
        return re.sub(r"[a-z]+", lambda m: m.group(0).upper(), number)

    @classmethod
    def _code_from_value(cls, value: str) -> str:
        parsed = cls._parse_code_parts(value)
        if not parsed:
            return ""
        prefix, digits = parsed
        normalized = f"{prefix}-{cls._normalize_digits_for_number(digits)}"
        return cls._normalize_keyword(normalized)

    @classmethod
    def _number_from_url(cls, detail_url: str) -> str:
        slug = cls._extract_slug(detail_url)
        return cls._normalize_number_case(slug)

    @classmethod
    def _extract_external_id(cls, detail_url: str) -> str:
        path_parts = cls._extract_detail_path_parts(detail_url)
        for part in path_parts:
            if part.lower().startswith("dm"):
                return part.lower()
        if path_parts:
            return path_parts[-1].lower()
        return ""

    @classmethod
    def _is_soft_404_page(cls, html: Selector) -> bool:
        og_title = (
            extract_text(html, "//meta[@property='og:title']/@content", "normalize-space(//title)").strip().lower()
        )
        og_image = extract_text(html, "//meta[@property='og:image']/@content").strip().lower()

        h1_texts = [text.strip().lower() for text in html.xpath("//h1//text()").getall() if text and text.strip()]
        p_texts = [text.strip().lower() for text in html.xpath("//p//text()").getall() if text and text.strip()]
        text_blob = " ".join(h1_texts + p_texts)

        has_404_code = bool(re.search(r"(^|\s)404(\s|$)", text_blob))
        has_not_found_text = any(marker.lower() in text_blob for marker in cls.SOFT_404_TEXT_MARKERS)
        is_generic_title = any(marker in og_title for marker in cls.SOFT_404_TITLE_MARKERS)
        is_logo_thumb = "logo-square.png" in og_image

        if has_not_found_text and has_404_code:
            return True
        return is_generic_title and is_logo_thumb and has_404_code

    def _build_direct_detail_url(self, number: str) -> str:
        raw_number = (number or "").strip()
        detail_url = f"{self.base_url}/{quote(raw_number)}"
        return self._ensure_cn_detail_url(detail_url)

    def _build_search_url(self, number: str) -> str:
        raw_number = (number or "").strip()
        return f"{self.base_url}/search/{quote(raw_number)}"

    @classmethod
    def _normalize_number_for_uncensored_judge(cls, number: str) -> str:
        raw_number = (number or "").strip()
        if not raw_number:
            return ""

        try:
            normalized = get_file_number(raw_number, [])
        except Exception:
            normalized = raw_number

        normalized = (normalized or "").strip().lower().replace("_", "-")
        if not normalized:
            return ""

        parsed = cls._parse_code_parts(normalized)
        if parsed:
            prefix, digits = parsed
            return f"{prefix}-{cls._normalize_digits_for_number(digits)}"

        if match := re.match(r"^(\d{6}[-_]\d{3,4})", normalized):
            return match.group(1)
        return normalized

    @classmethod
    def _should_use_uncensored_search(cls, number: str, mosaic: str = "") -> bool:
        _ = mosaic
        normalized_number = cls._normalize_number_for_uncensored_judge(number)
        if not normalized_number:
            return False
        if is_uncensored(normalized_number):
            return True
        return bool(cls.UNCENSORED_DATE_PATTERN.fullmatch(normalized_number))

    @classmethod
    def _is_search_mode_url(cls, url: str) -> bool:
        return "/search/" in (urlparse(url).path or "").lower()

    @staticmethod
    def _normalize_uncensored_keyword(number: str) -> str:
        return (number or "").strip().lower().replace("_", "-")

    @staticmethod
    def _normalize_hostname(host: str) -> str:
        return (host or "").lower().removeprefix("www.")

    def _is_search_result_detail_href(self, href: str) -> bool:
        href = (href or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            return False

        detail_url = urljoin(self.base_url, href)
        parsed = urlparse(detail_url)
        if parsed.scheme not in {"http", "https"}:
            return False

        base_host = self._normalize_hostname(urlparse(self.base_url).netloc)
        if self._normalize_hostname(parsed.netloc) != base_host:
            return False

        if parsed.query or parsed.fragment:
            return False

        path_parts = self._extract_detail_path_parts(detail_url)
        if not path_parts:
            return False

        first = path_parts[0].lower().strip()
        if first in self.SEARCH_BLACKLIST_PREFIXES:
            return False

        if len(path_parts) > 2:
            return False
        if len(path_parts) == 2 and not path_parts[0].lower().startswith("dm"):
            return False

        return bool(re.search(r"\d", path_parts[-1]))

    def _extract_first_detail_url_from_search(self, html: Selector, expected_keyword: str = "") -> str:
        hrefs = html.xpath("//a[@href]/@href").getall()
        candidates: list[str] = []
        seen: set[str] = set()
        for href in hrefs:
            if self._is_search_result_detail_href(href):
                detail_url = self._ensure_cn_detail_url(urljoin(self.base_url, href.strip()))
                if detail_url not in seen:
                    seen.add(detail_url)
                    candidates.append(detail_url)

        if not candidates:
            return ""

        if expected_keyword:
            for detail_url in candidates:
                detail_slug = self._extract_slug(detail_url).lower().replace("_", "-")
                if expected_keyword in detail_slug:
                    return detail_url

        return candidates[0]

    @override
    async def _generate_search_url(self, ctx) -> list[str] | str | None:
        number = ctx.input.number.strip()
        if not number:
            raise CralwerException("番号为空")

        if self._should_use_uncensored_search(number, ctx.input.mosaic):
            search_url = self._build_search_url(number)
            self._log(f"生成无码搜索地址: {search_url}")
            return [search_url]

        detail_url = self._build_direct_detail_url(number)
        self._log(f"生成直达详情页地址: {detail_url}")
        return [detail_url]

    @override
    async def _parse_search_page(self, ctx, html: Selector, search_url: str) -> list[str] | str | None:
        if not self._is_search_mode_url(search_url):
            return [search_url]

        expected_keyword = self._normalize_uncensored_keyword(ctx.input.number)
        detail_url = self._extract_first_detail_url_from_search(html, expected_keyword)
        if detail_url:
            ctx.debug(f"MissAV 无码搜索命中首个详情页 URL: {detail_url}")
            return [detail_url]

        ctx.debug("MissAV 无码搜索页未提取到有效详情页 URL")
        return None

    @override
    async def _search(self, ctx, search_urls: list[str]) -> list[str] | None:
        if not search_urls:
            return None

        if any(self._is_search_mode_url(url) for url in search_urls):
            detail_urls = await super()._search(ctx, search_urls)
            if detail_urls:
                return detail_urls
            fallback_url = self._build_direct_detail_url(ctx.input.number)
            ctx.debug(f"MissAV 无码搜索无结果，回退直达详情页 URL: {fallback_url}")
            return [fallback_url]

        ctx.debug(f"MissAV 跳过搜索页，直接使用详情页 URL: {search_urls}")
        return search_urls

    @override
    async def _parse_detail_page(self, ctx, html: Selector, detail_url: str) -> CrawlerData | None:
        if self._is_soft_404_page(html):
            raise CralwerException(f"MissAV 详情页不存在或已下架: {detail_url}")

        canonical_url = extract_text(html, "//meta[@property='og:url']/@content")
        final_detail_url = canonical_url or detail_url
        data = await self.parser.parse(ctx, html, external_id=self._extract_external_id(final_detail_url))

        input_code = self._code_from_value(ctx.input.number)
        canonical_code = self._code_from_value(self._extract_slug(final_detail_url))
        data_code = self._code_from_value(data.number)
        target_code = canonical_code or data_code
        if input_code and target_code and input_code != target_code:
            raise CralwerException(
                f"直达跳转结果与输入番号不一致: input={ctx.input.number}, target={data.number or self._extract_slug(final_detail_url)}"
            )

        canonical_number = self._number_from_url(final_detail_url)
        if canonical_number:
            data.number = canonical_number

        if self._should_use_uncensored_search(ctx.input.number, ctx.input.mosaic):
            expected_keyword = self._normalize_uncensored_keyword(ctx.input.number)
            detail_slug = self._extract_slug(final_detail_url).lower().replace("_", "-")
            if expected_keyword and expected_keyword not in detail_slug:
                raise CralwerException(f"无码搜索详情页校验失败: input={ctx.input.number}, detail={final_detail_url}")

        if data.number:
            data.external_id = data.number
        elif ctx.input.number.strip():
            data.external_id = ctx.input.number.strip()

        self._log(f"详情解析完成: {data.number or ctx.input.number}")
        return data

    @override
    async def post_process(self, ctx, res):
        if not res.number:
            res.number = self._normalize_number_case(ctx.input.number)
        else:
            res.number = self._normalize_number_case(res.number)
        if not res.originaltitle:
            res.originaltitle = res.title
        if not res.originalplot:
            res.originalplot = res.outline
        if not res.poster:
            res.poster = res.thumb
        if not res.publisher:
            res.publisher = res.studio
        res.mosaic = ""
        if not res.year and (match := re.search(r"\d{4}", res.release or "")):
            res.year = match.group()
        return res
