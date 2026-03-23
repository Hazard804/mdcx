import json
import re
from typing import Any, override
from urllib.parse import quote, urljoin

from parsel import Selector

from mdcx.base.web import check_url, get_url_content_length, is_dmm_image_url, normalize_media_url

from ..config.enums import DownloadableFile
from ..config.manager import manager
from ..config.models import Website
from ..signals import signal
from .base import BaseCrawler, CralwerException, CrawlerData

SEARCH_FIRST_RESULT_ID_XPATH = "/html/body/div/div/main/div/div[2]/div[2]/div/div/div[1]/div[1]/div[1]/div"


class AvbaseCrawler(BaseCrawler):
    @staticmethod
    def _log(message: str) -> None:
        signal.add_log(f"🌐 [AVBASE] {message}")

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.AVBASE

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.avbase.net"

    @override
    async def _generate_search_url(self, ctx) -> list[str] | str | None:
        number = ctx.input.number.strip()
        if not number:
            raise CralwerException("番号为空")
        return f"{self.base_url}/works?q={quote(number)}"

    @override
    async def _parse_search_page(self, ctx, html: Selector, search_url: str) -> list[str] | str | None:
        first_result_id = html.xpath(f"normalize-space({SEARCH_FIRST_RESULT_ID_XPATH})").get(default="").strip()
        if first_result_id and ":" in first_result_id:
            detail_url = f"{self.base_url}/works/{first_result_id}"
            ctx.debug(f"通过固定 XPath 命中首个结果 ID: {first_result_id}")
            return [detail_url]

        href = html.xpath(
            '(//a[starts-with(@href, "/works/") and not(starts-with(@href, "/works/date"))])[1]/@href'
        ).get(default="")
        if href:
            detail_url = urljoin(self.base_url, href)
            ctx.debug(f"固定 XPath 未命中，回退到首个作品链接: {detail_url}")
            return [detail_url]

        return None

    @override
    async def _parse_detail_page(self, ctx, html: Selector, detail_url: str) -> CrawlerData | None:
        next_data_text = html.xpath('//script[@id="__NEXT_DATA__"]/text()').get(default="")
        if not next_data_text:
            raise CralwerException("详情页缺少 __NEXT_DATA__")

        try:
            next_data = json.loads(next_data_text)
        except json.JSONDecodeError as error:
            raise CralwerException(f"__NEXT_DATA__ 解析失败: {error}") from error

        work = ((next_data.get("props") or {}).get("pageProps") or {}).get("work") or {}
        if not work:
            raise CralwerException("详情页 __NEXT_DATA__ 中缺少 work 数据")

        products = [product_item for product_item in (work.get("products") or []) if isinstance(product_item, dict)]
        product = self._pick_product(products)

        number = (work.get("work_id") or ctx.input.number).strip()
        prefix = (work.get("prefix") or "").strip()
        external_id = f"{prefix}:{number}" if prefix and number else number
        title = (work.get("title") or product.get("title") or "").strip()
        outline = (
            str(work.get("note") or "").strip()
            or self._extract_description(product)
            or self._extract_best_description(products)
        )
        actors = self._extract_actor_names(work.get("casts") or [])
        directors = self._split_names((product.get("iteminfo") or {}).get("director"))
        tags = self._extract_tag_names(work)
        release = self._parse_release_date(product.get("date") or work.get("min_date") or "")
        runtime = self._parse_runtime((product.get("iteminfo") or {}).get("volume") or "")

        studio = self._extract_nested_name(product, "maker")
        publisher = self._extract_nested_name(product, "label")
        series = self._extract_nested_name(product, "series")

        thumb = self._to_absolute_url(product.get("image_url") or "")
        poster = self._to_poster_url(thumb)
        extrafanart, extrafanart_product = self._collect_extrafanart(products, product)
        trailer = self._to_absolute_url(product.get("trailer_url") or "")

        if products:
            picked_product_id = str(product.get("product_id") or "")
            picked_source = str(product.get("source") or "")
            ctx.debug(
                f"详情页 products 数量: {len(products)}; 当前选用: source={picked_source}, product_id={picked_product_id}"
            )
            if extrafanart_product:
                extrafanart_product_id = str(extrafanart_product.get("product_id") or "")
                extrafanart_source = str(extrafanart_product.get("source") or "")
                ctx.debug(
                    f"剧照来源: source={extrafanart_source}, product_id={extrafanart_product_id}, count={len(extrafanart)}"
                )
            if outline:
                ctx.debug(f"简介长度: {len(outline)}")

        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            directors=directors,
            outline=outline,
            originalplot=outline,
            thumb=thumb,
            poster=poster,
            extrafanart=extrafanart,
            release=release,
            runtime=runtime,
            tags=tags,
            studio=studio,
            publisher=publisher or studio,
            series=series,
            trailer=trailer,
            image_cut="right",
            image_download=False,
            external_id=external_id,
        )

    @override
    async def post_process(self, ctx, res):
        if not res.number:
            res.number = ctx.input.number
        if not res.originaltitle:
            res.originaltitle = res.title
        if not res.originalplot:
            res.originalplot = res.outline

        res.thumb, res.poster = self._normalize_thumb_poster(res.thumb, res.poster)

        original_thumb = normalize_media_url(str(res.thumb or "").strip())
        upgraded_thumb = await self._upgrade_dmm_image_url(ctx, original_thumb)
        if upgraded_thumb and upgraded_thumb != original_thumb:
            self._log(f"封面图升级为高清源: {upgraded_thumb}")
        res.thumb = upgraded_thumb
        res.thumb, res.poster = self._normalize_thumb_poster(res.thumb, res.poster)
        res.poster = await self._resolve_poster_url(res.thumb, res.poster)

        if DownloadableFile.EXTRAFANART in manager.config.download_files and res.extrafanart:
            res.extrafanart = await self._sanitize_extrafanart_urls(list(res.extrafanart))

        studio_text = str(res.studio or "").upper()
        title_text = str(res.title or "").upper()
        input_mosaic = str(ctx.input.mosaic or "")
        is_youma = res.mosaic in ["有码", "有碼"] or input_mosaic in ["有码", "有碼"]
        use_youma_poster = (
            is_youma
            and DownloadableFile.YOUMA_USE_POSTER in manager.config.download_files
            and DownloadableFile.IGNORE_YOUMA not in manager.config.download_files
        )
        is_sod_studio = "SOD" in studio_text
        is_vr_title = "VR" in title_text
        res.image_download = use_youma_poster or is_vr_title or is_sod_studio
        if use_youma_poster:
            self._log("图片[有码策略]: 启用「有码优先使用 Poster」，跳过 SOD/VR 判定")

        if res.image_download and not res.poster:
            self._log("图片[Poster失效]: 直下封面无可用候选，改为裁剪模式")
            res.image_download = False

        if not use_youma_poster and is_sod_studio and res.poster and res.thumb:
            poster_size = await self._get_url_content_length(res.poster)
            thumb_size = await self._get_url_content_length(res.thumb)
            if poster_size and thumb_size:
                if poster_size < thumb_size * 0.5:
                    res.image_download = is_vr_title
                    self._log(f"SOD 图片判定: ps={poster_size}B, pl={thumb_size}B，改为裁剪模式")
                else:
                    self._log(f"SOD 图片判定: ps={poster_size}B, pl={thumb_size}B，保持直接下载")
            else:
                self._log("SOD 图片判定: 无法获取 ps/pl 大小，保持直接下载")

        if not res.publisher:
            res.publisher = res.studio
        if res.release and len(res.release) >= 4 and not res.year:
            res.year = res.release[:4]
        return res

    async def _get_url_content_length(self, url: str) -> int | None:
        return await get_url_content_length(url)

    def _pick_product(self, products: list[Any]) -> dict[str, Any]:
        valid_products = [product_item for product_item in products if isinstance(product_item, dict)]
        if not valid_products:
            return {}
        return max(valid_products, key=self._product_score)

    def _product_score(self, product: dict[str, Any]) -> int:
        score = 0
        source = str(product.get("source") or "")
        source_lower = source.lower()
        if "dmm.co.jp" in source_lower or "fanza" in source_lower:
            score += 20
        if product.get("image_url"):
            score += 5
        if (product.get("iteminfo") or {}).get("volume"):
            score += 2
        score += len(product.get("sample_image_urls") or [])
        return score

    @staticmethod
    def _extract_description(product: dict[str, Any]) -> str:
        iteminfo = product.get("iteminfo") or {}
        if not isinstance(iteminfo, dict):
            return ""
        return str(iteminfo.get("description") or "").strip()

    def _extract_best_description(self, products: list[dict[str, Any]]) -> str:
        if not products:
            return ""
        candidates: list[dict[str, Any]] = []
        for product_item in products:
            if self._extract_description(product_item):
                candidates.append(product_item)
        if not candidates:
            return ""
        best = self._pick_product(candidates)
        return self._extract_description(best)

    def _collect_extrafanart(
        self, products: list[dict[str, Any]], preferred_product: dict[str, Any]
    ) -> tuple[list[str], dict[str, Any] | None]:
        best_images: list[str] = []
        best_product: dict[str, Any] | None = None
        best_score: tuple[int, int, int] = (0, 0, 0)

        for product_item in products:
            sample_items = product_item.get("sample_image_urls") or []
            sample_images = self._extract_sample_image_urls(sample_items)
            if not sample_images:
                continue

            current_score = (
                len(sample_images),
                1 if product_item is preferred_product else 0,
                self._product_score(product_item),
            )
            if current_score > best_score:
                best_score = current_score
                best_images = sample_images
                best_product = product_item

        return best_images, best_product

    @staticmethod
    def _extract_actor_names(casts: list[Any]) -> list[str]:
        names: list[str] = []
        for cast_item in casts:
            if not isinstance(cast_item, dict):
                continue
            actor = cast_item.get("actor")
            if isinstance(actor, dict):
                name = str(actor.get("name") or "").strip()
                if name and name not in names:
                    names.append(name)
        return names

    @staticmethod
    def _extract_tag_names(work: dict[str, Any]) -> list[str]:
        names: list[str] = []
        for key in ("genres", "tags"):
            for item in work.get(key) or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if name and name not in names:
                    names.append(name)
        return names

    @staticmethod
    def _extract_nested_name(product: dict[str, Any], field: str) -> str:
        value = product.get(field)
        if isinstance(value, dict):
            return str(value.get("name") or "").strip()
        return ""

    def _to_absolute_url(self, url: str) -> str:
        if not url:
            return ""
        return urljoin(self.base_url, url)

    @staticmethod
    def _to_poster_url(thumb: str) -> str:
        if not thumb:
            return ""
        if thumb.endswith("pl.jpg"):
            return thumb[:-6] + "ps.jpg"
        return thumb

    @staticmethod
    def _normalize_thumb_poster(thumb: str | None, poster: str | None) -> tuple[str, str]:
        thumb_url = str(thumb or "").strip()
        poster_url = str(poster or "").strip()

        for candidate_url in (thumb_url, poster_url):
            split = AvbaseCrawler._split_cover_base_url(candidate_url)
            if split:
                base_url, _ = split
                return base_url + "pl.jpg", base_url + "ps.jpg"

        if thumb_url and not poster_url:
            return thumb_url, thumb_url
        if poster_url and not thumb_url:
            return poster_url, poster_url
        return thumb_url, poster_url

    @staticmethod
    def _split_cover_base_url(url: str) -> tuple[str, str] | None:
        if url.endswith("pl.jpg"):
            return url[:-6], "pl"
        if url.endswith("ps.jpg"):
            return url[:-6], "ps"
        return None

    async def _upgrade_dmm_image_url(self, ctx, image_url: str) -> str:
        normalized = normalize_media_url(image_url)
        if not normalized:
            return ""
        if "pics.dmm.co.jp" in normalized:
            aws_url = normalized.replace("pics.dmm.co.jp", "awsimgsrc.dmm.co.jp/pics_dig").replace("/adult/", "/")
            if validated_aws := await check_url(aws_url):
                return str(validated_aws)
        if is_dmm_image_url(normalized):
            if validated_original := await check_url(normalized):
                return str(validated_original)
            self._log(f"高清图校验失败，丢弃原图: {normalized}")
            return ""
        return normalized

    async def _resolve_poster_url(self, thumb: str, poster: str) -> str:
        candidates = list(
            dict.fromkeys(
                filter(
                    None,
                    [
                        normalize_media_url(str(poster or "").strip()),
                        normalize_media_url(self._to_poster_url(str(thumb or "").strip())),
                    ],
                )
            )
        )
        for candidate in candidates:
            if is_dmm_image_url(candidate):
                if validated := await check_url(candidate):
                    return str(validated)
                continue
            return candidate
        return ""

    async def _sanitize_extrafanart_urls(self, image_urls: list[str]) -> list[str]:
        valid_urls: list[str] = []
        for image_url in image_urls:
            normalized = normalize_media_url(self._to_absolute_url(image_url))
            if not normalized:
                continue
            if is_dmm_image_url(normalized):
                validated = await check_url(normalized)
                if not validated:
                    continue
                normalized = str(validated)
            if normalized not in valid_urls:
                valid_urls.append(normalized)
        return valid_urls

    def _extract_sample_image_urls(self, sample_image_urls: list[Any]) -> list[str]:
        images: list[str] = []
        for item in sample_image_urls:
            url = ""
            if isinstance(item, dict):
                url = str(item.get("l") or item.get("s") or "").strip()
            elif isinstance(item, str):
                url = item.strip()
            if not url:
                continue
            abs_url = self._to_absolute_url(url)
            if abs_url not in images:
                images.append(abs_url)
        return images

    @staticmethod
    def _parse_runtime(raw: str) -> str:
        raw = str(raw).strip()
        if not raw:
            return ""

        if match := re.search(r"(\d{1,2})[:：](\d{1,2})[:：](\d{1,2})", raw):
            hours, minutes, seconds = (int(group) for group in match.groups())
            total_minutes = hours * 60 + minutes
            if total_minutes == 0 and seconds > 0:
                return "1"
            return str(total_minutes)

        if match := re.search(r"\d+", raw):
            return match.group()
        return raw

    @staticmethod
    def _split_names(raw: str | None) -> list[str]:
        if not raw:
            return []
        names: list[str] = []
        for part in re.split(r"[,，、/／|]", str(raw)):
            name = part.strip()
            if name and name not in names:
                names.append(name)
        return names

    @staticmethod
    def _parse_release_date(raw: str) -> str:
        raw = str(raw).strip()
        if not raw:
            return ""

        if match := re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", raw):
            year, month, day = match.groups()
            return f"{year}-{int(month):02d}-{int(day):02d}"

        if match := re.search(r"^[A-Za-z]{3}\s+([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})", raw):
            month_name, day, year = match.groups()
            month = {
                "jan": 1,
                "feb": 2,
                "mar": 3,
                "apr": 4,
                "may": 5,
                "jun": 6,
                "jul": 7,
                "aug": 8,
                "sep": 9,
                "oct": 10,
                "nov": 11,
                "dec": 12,
            }.get(month_name.lower())
            if month:
                return f"{year}-{month:02d}-{int(day):02d}"

        return raw
