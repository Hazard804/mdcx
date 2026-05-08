"""
刮削流程内的媒体资源获取与内存复用。
"""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os
from PIL import Image

from ..base.web import _build_dmm_probe_url, _is_invalid_image_redirect_url, is_dmm_image_url, normalize_media_url
from ..config.manager import manager
from ..models.log_buffer import LogBuffer


@dataclass(slots=True)
class FetchedImage:
    url: str
    content: bytes
    size: tuple[int, int] = (0, 0)


class MediaResourceContext:
    """单次刮削图片资源上下文，按 URL 复用已获取的图片内容。"""

    def __init__(self):
        self._images: dict[str, FetchedImage] = {}

    def close(self) -> None:
        self._images.clear()

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
        if true_url != normalized_url:
            self._images[true_url] = image
        return image

    async def fetch_bytes(self, url: str) -> bytes | None:
        image = await self.fetch_image(url)
        return image.content if image is not None else None

    async def get_size(self, url: str) -> tuple[int, int]:
        image = await self.fetch_image(url)
        return image.size if image is not None else (0, 0)

    async def probe_size(self, url: str) -> tuple[int, int]:
        """轻量探测图片尺寸，不缓存完整内容。"""
        normalized_url = self.normalize_url(url)
        if not normalized_url:
            return 0, 0
        cached = self._images.get(normalized_url)
        if cached is not None:
            return cached.size

        request_url, added_probe = self._build_request_url(normalized_url)
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
                    return 0, 0
                return await self._read_stream_size(response)
            finally:
                await client._close_response(response)

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
