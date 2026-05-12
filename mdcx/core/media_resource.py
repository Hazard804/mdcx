"""
刮削流程内的媒体资源获取与内存复用。
"""

import asyncio
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os
from PIL import Image

from ..base.web import (
    _build_dmm_probe_url,
    _is_invalid_image_redirect_url,
    _parse_content_length,
    _should_retry_link_error,
    is_dmm_image_url,
    normalize_media_url,
)
from ..config.manager import manager
from ..models.log_buffer import LogBuffer


@dataclass(slots=True)
class FetchedImage:
    url: str
    content: bytes
    size: tuple[int, int] = (0, 0)


MAX_IMAGE_PROBE_BYTES = 512 * 1024


class MediaResourceContext:
    """单次刮削媒体资源上下文，按 URL 复用已获取的内容与探测元数据。"""

    def __init__(self):
        self._images: dict[str, FetchedImage] = {}
        self._image_sizes: dict[tuple[str, bool], tuple[int, int]] = {}
        self._content_lengths: dict[str, int | None] = {}
        self._validated_image_urls: dict[str, str | None] = {}

    def close(self) -> None:
        self._images.clear()
        self._image_sizes.clear()
        self._content_lengths.clear()
        self._validated_image_urls.clear()

    @staticmethod
    def normalize_url(url: str) -> str:
        return normalize_media_url(url)

    async def fetch_image(self, url: str) -> FetchedImage | None:
        normalized_url = self.normalize_url(url)
        if not normalized_url:
            return None
        cached = self._images.get(normalized_url)
        if cached is not None:
            return cached

        # 完整下载不能使用 DMM 探测参数，否则会把 120x90 探测图写入封面缓存。
        request_url, added_probe = normalized_url, False
        async with manager.acquire_computed() as computed:
            response, error = await computed.async_client.request("GET", request_url)
        if response is None:
            if error:
                LogBuffer.log().write(f"\n 🟡 图片读取失败: {error}")
            return None

        true_url = normalize_media_url(str(response.url), strip_dmm_probe_params=added_probe)
        if self._is_invalid_image_url(normalized_url, true_url):
            LogBuffer.log().write(f"\n 💡 图片已失效: {true_url}")
            return None

        if not response.content:
            LogBuffer.log().write(f"\n 🟡 图片读取失败: empty content {true_url}")
            return None

        image = FetchedImage(true_url, response.content, await self._read_size(response.content))
        self._images[normalized_url] = image
        self._image_sizes[(normalized_url, False)] = image.size
        if true_url != normalized_url:
            self._images[true_url] = image
            self._image_sizes[(true_url, False)] = image.size
        return image

    async def fetch_bytes(self, url: str) -> bytes | None:
        image = await self.fetch_image(url)
        return image.content if image is not None else None

    async def get_size(self, url: str) -> tuple[int, int]:
        image = await self.fetch_image(url)
        return image.size if image is not None else (0, 0)

    async def probe_size(self, url: str) -> tuple[int, int]:
        """轻量探测图片尺寸，不缓存完整内容。"""
        return await self._probe_size(url, use_dmm_probe=True)

    async def probe_original_size(self, url: str) -> tuple[int, int]:
        """探测原图尺寸，不使用 DMM 缩略参数。"""
        return await self._probe_size(url, use_dmm_probe=False)

    async def check_image_url(self, url: str) -> str | None:
        """校验图片 URL，同一文件内复用校验结果。DMM 使用小图探测参数。"""
        normalized_url = self.normalize_url(url)
        if not normalized_url:
            return None
        if normalized_url in self._validated_image_urls:
            return self._validated_image_urls[normalized_url]
        if not is_dmm_image_url(normalized_url):
            self._validated_image_urls[normalized_url] = normalized_url
            return normalized_url

        validated = await self._check_dmm_image_url(normalized_url)
        self._validated_image_urls[normalized_url] = validated
        if validated and validated != normalized_url:
            self._validated_image_urls[validated] = validated
        return validated

    async def _probe_size(self, url: str, *, use_dmm_probe: bool) -> tuple[int, int]:
        normalized_url = self.normalize_url(url)
        if not normalized_url:
            return 0, 0
        cache_key = (normalized_url, use_dmm_probe)
        if cache_key in self._image_sizes:
            return self._image_sizes[cache_key]
        cached = self._images.get(normalized_url)
        if cached is not None:
            return cached.size

        request_url, added_probe = self._build_request_url(normalized_url) if use_dmm_probe else (normalized_url, False)
        async with manager.acquire_computed() as computed:
            client = computed.async_client
            response, error = await client.request("GET", request_url, stream=True)
            if response is None:
                if error:
                    LogBuffer.log().write(f"\n 🟡 图片尺寸探测失败: {error}")
                return 0, 0

            true_url = normalize_media_url(str(response.url), strip_dmm_probe_params=added_probe)
            try:
                if self._is_invalid_image_url(normalized_url, true_url):
                    LogBuffer.log().write(f"\n 💡 图片已失效: {true_url}")
                    self._image_sizes[cache_key] = (0, 0)
                    return 0, 0
                size = await self._read_stream_size(response)
                self._image_sizes[cache_key] = size
                true_cache_key = (true_url, use_dmm_probe)
                self._image_sizes[true_cache_key] = size
                return size
            finally:
                await client._close_response(response)

    async def get_content_length(self, url: str) -> int | None:
        normalized_url = self.normalize_url(url)
        if not normalized_url:
            return None
        if normalized_url in self._content_lengths:
            return self._content_lengths[normalized_url]
        cached = self._images.get(normalized_url)
        if cached is not None:
            length = len(cached.content)
            self._content_lengths[normalized_url] = length
            return length

        length = await self._fetch_content_length(normalized_url)
        self._content_lengths[normalized_url] = length
        return length

    async def _fetch_content_length(self, url: str) -> int | None:
        retry_delays = [0.5, 1.0, 1.5]
        async with manager.acquire_computed() as computed:
            client = computed.async_client
            if is_dmm_image_url(url):
                return await self._fetch_dmm_content_length(client, url, retry_delays)

            for attempt, delay in enumerate(retry_delays, start=1):
                response, error = await client.request("HEAD", url, retry_count=1)
                if response is not None:
                    if content_length := _parse_content_length(response.headers.get("Content-Length")):
                        return content_length
                elif "HTTP 405" in str(error):
                    break
                elif not _should_retry_link_error(error) or attempt == len(retry_delays):
                    return None

                if attempt < len(retry_delays):
                    await asyncio.sleep(delay)

            for attempt, delay in enumerate(retry_delays, start=1):
                response, error = await client.request("GET", url, retry_count=1)
                if response is None:
                    if not _should_retry_link_error(error) or attempt == len(retry_delays):
                        return None
                    await asyncio.sleep(delay)
                    continue

                if content_length := _parse_content_length(response.headers.get("Content-Length")):
                    return content_length
                if response.content and len(response.content) > 0:
                    return len(response.content)

                if attempt < len(retry_delays):
                    await asyncio.sleep(delay)
        return None

    async def _fetch_dmm_content_length(self, client: Any, url: str, retry_delays: list[float]) -> int | None:
        for attempt, delay in enumerate(retry_delays, start=1):
            response, error = await client.request("GET", url, retry_count=1)
            if response is None:
                if not _should_retry_link_error(error) or attempt == len(retry_delays):
                    return None
                await asyncio.sleep(delay)
                continue

            true_url = normalize_media_url(str(response.url))
            if true_url and true_url != url and true_url not in self._content_lengths:
                self._content_lengths[true_url] = None
            if self._is_invalid_image_url(url, true_url):
                return None

            if content_length := _parse_content_length(response.headers.get("Content-Length")):
                if true_url:
                    self._content_lengths[true_url] = content_length
                return content_length
            if response.content and len(response.content) > 0:
                content_length = len(response.content)
                if true_url:
                    self._content_lengths[true_url] = content_length
                return content_length

            if attempt < len(retry_delays):
                await asyncio.sleep(delay)
        return None

    async def _check_dmm_image_url(self, url: str) -> str | None:
        request_url, added_probe = self._build_request_url(url)
        retry_delays = [0.6, 1.2, 1.8]
        async with manager.acquire_computed() as computed:
            client = computed.async_client
            for attempt, delay in enumerate(retry_delays, start=1):
                response, error = await client.request("GET", request_url, retry_count=1)
                if response is None:
                    if not _should_retry_link_error(error) or attempt == len(retry_delays):
                        return None
                    await asyncio.sleep(delay)
                    continue

                true_url = normalize_media_url(str(response.url), strip_dmm_probe_params=added_probe)
                if self._is_invalid_image_url(url, true_url):
                    return None

                if _parse_content_length(response.headers.get("Content-Length")):
                    return true_url
                if response.content and len(response.content) > 0:
                    return true_url

                if attempt < len(retry_delays):
                    await asyncio.sleep(delay)
        return None

    async def open_rgb_image(self, url: str) -> Image.Image | None:
        image = await self.fetch_image(url)
        if image is None:
            return None
        try:
            with Image.open(BytesIO(image.content)) as img:
                img.load()
                return img.convert("RGB")
        except Exception:
            return None

    async def save_image(self, url: str, file_path: Path, folder_path: Path) -> bool:
        image = await self.fetch_image(url)
        if image is None:
            LogBuffer.log().write(f"\n 🥺 Download failed! {url}")
            return False

        if not await aiofiles.os.path.exists(folder_path):
            await aiofiles.os.makedirs(folder_path)

        if self._should_convert_to_jpg(url, file_path):
            return await self._save_converted_jpg(image, file_path)

        try:
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(image.content)
            return True
        except Exception as e:
            LogBuffer.log().write(f"\n 🔴 文件写入失败: {url} {file_path} {str(e)}")
            return False

    @staticmethod
    async def _read_size(content: bytes) -> tuple[int, int]:
        try:
            with Image.open(BytesIO(content)) as img:
                return img.size
        except Exception:
            return 0, 0

    @staticmethod
    async def _read_stream_size(response: Any) -> tuple[int, int]:
        file_head = BytesIO()
        chunk_size = 1024 * 10
        try:
            if response.status_code != 200:
                return 0, 0
            for chunk in response.iter_content(chunk_size):
                file_head.write(await chunk)
                if file_head.tell() > MAX_IMAGE_PROBE_BYTES:
                    return 0, 0
                try:
                    with Image.open(file_head) as img:
                        return img.size
                except Exception:
                    continue
        except Exception:
            return 0, 0
        return 0, 0

    @staticmethod
    def _should_convert_to_jpg(url: str, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".jpg" and ".webp" in url.lower()

    @staticmethod
    async def _save_converted_jpg(image: FetchedImage, file_path: Path) -> bool:
        try:
            with Image.open(BytesIO(image.content)) as img:
                converted = None
                if img.mode == "RGBA":
                    converted = img.convert("RGB")
                save_img = converted or img
                try:
                    save_img.save(file_path, quality=95, subsampling=0)
                finally:
                    if converted is not None:
                        converted.close()
            return True
        except Exception as e:
            LogBuffer.log().write(f"\n 🔴 WebP转换失败: {image.url} {file_path} {str(e)}")
            return False

    @staticmethod
    def _is_invalid_image_url(request_url: str, true_url: str) -> bool:
        if _is_invalid_image_redirect_url(true_url):
            return True
        return is_dmm_image_url(request_url) and _is_invalid_image_redirect_url(true_url)

    @staticmethod
    def _build_request_url(url: str) -> tuple[str, bool]:
        if is_dmm_image_url(url):
            return _build_dmm_probe_url(url)
        return url, False
