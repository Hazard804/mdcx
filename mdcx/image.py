import asyncio
import traceback
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import aiofiles.os
from PIL import Image, ImageFilter
from PyQt6.QtCore import QObject, QSize, pyqtSignal
from PyQt6.QtGui import QImage, QImageReader, QPixmap

from .signals import signal
from .utils.file import delete_file_async

POSTER_PREVIEW_SIZE = QSize(156, 220)
THUMB_PREVIEW_SIZE = QSize(328, 220)


@dataclass(frozen=True)
class _PreviewCacheKey:
    path: Path
    mtime_ns: int
    file_size: int
    poster: bool


@dataclass
class _PreviewCacheEntry:
    image: QImage
    msg: str
    width: int
    height: int
    bytes_size: int


class _PreviewImageCache:
    def __init__(self, max_items: int = 80, max_bytes: int = 64 * 1024 * 1024):
        self.max_items = max_items
        self.max_bytes = max_bytes
        self._items: OrderedDict[_PreviewCacheKey, _PreviewCacheEntry] = OrderedDict()
        self._bytes = 0

    def get(self, key: _PreviewCacheKey) -> _PreviewCacheEntry | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        self._items.move_to_end(key)
        return entry

    def put(self, key: _PreviewCacheKey, entry: _PreviewCacheEntry) -> None:
        old_entry = self._items.pop(key, None)
        if old_entry is not None:
            self._bytes -= old_entry.bytes_size
        self._items[key] = entry
        self._bytes += entry.bytes_size
        self._trim()

    def _trim(self) -> None:
        while self._items and (len(self._items) > self.max_items or self._bytes > self.max_bytes):
            _, entry = self._items.popitem(last=False)
            self._bytes -= entry.bytes_size

    def clear(self) -> None:
        self._items.clear()
        self._bytes = 0


def _preview_target_size(original_width: int, original_height: int, poster: bool) -> QSize:
    max_size = POSTER_PREVIEW_SIZE if poster else THUMB_PREVIEW_SIZE
    if original_width <= 0 or original_height <= 0:
        return max_size
    if original_width / original_height > max_size.width() / max_size.height():
        width = max_size.width()
        height = int(max_size.width() * original_height / original_width)
    else:
        width = int(max_size.height() * original_width / original_height)
        height = max_size.height()
    return QSize(max(width, 1), max(height, 1))


def _preview_placeholder(poster: bool, text: str | None = None) -> list:
    max_size = POSTER_PREVIEW_SIZE if poster else THUMB_PREVIEW_SIZE
    default_text = "暂无封面图" if poster else "暂无缩略图"
    return [False, QImage(), text or default_text, max_size.width(), max_size.height()]


class PreviewImageLoader(QObject):
    loaded = pyqtSignal(int, list, list)

    def __init__(self, parent: QObject | None = None, max_items: int = 80, max_bytes: int = 64 * 1024 * 1024):
        super().__init__(parent)
        self._cache = _PreviewImageCache(max_items=max_items, max_bytes=max_bytes)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="PreviewImageLoader")

    def load(
        self,
        request_id: int,
        poster_path: Path | None,
        thumb_path: Path | None,
        poster_from: str = "",
        thumb_from: str = "",
    ) -> None:
        future = self._pool.submit(self._load_pair, poster_path, thumb_path, poster_from, thumb_from)
        future.add_done_callback(lambda done: self._emit_result(request_id, done))

    def shutdown(self) -> None:
        self._cache.clear()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _emit_result(self, request_id: int, future) -> None:
        try:
            poster_image, thumb_image = future.result()
        except Exception:
            signal.show_log_text(traceback.format_exc())
            poster_image = _preview_placeholder(True, "加载失败")
            thumb_image = _preview_placeholder(False, "加载失败")
        self.loaded.emit(request_id, poster_image, thumb_image)

    def _load_pair(
        self,
        poster_path: Path | None,
        thumb_path: Path | None,
        poster_from: str,
        thumb_from: str,
    ) -> tuple[list, list]:
        return (
            self._load_one(poster_path, poster=True, pic_from=poster_from),
            self._load_one(thumb_path, poster=False, pic_from=thumb_from),
        )

    def _load_one(self, pic_path: Path | None, poster: bool, pic_from: str = "") -> list:
        if not pic_path or not pic_path.exists():
            return _preview_placeholder(poster)

        try:
            stat = pic_path.stat()
            key = _PreviewCacheKey(
                path=pic_path.resolve(),
                mtime_ns=stat.st_mtime_ns,
                file_size=stat.st_size,
                poster=poster,
            )
            cached = self._cache.get(key)
            if cached is not None:
                return [True, cached.image, cached.msg, cached.width, cached.height]

            reader = QImageReader(pic_path.as_posix())
            reader.setAutoTransform(True)
            if not reader.canRead():
                return _preview_placeholder(poster, "封面图损坏" if poster else "缩略图损坏")

            original_size = reader.size()
            target_size = _preview_target_size(original_size.width(), original_size.height(), poster)
            image = reader.read()
            if image.isNull():
                return _preview_placeholder(poster, "封面图损坏" if poster else "缩略图损坏")

            msg = f"{pic_from.title()}: {original_size.width()}*{original_size.height()}/{int(stat.st_size / 1024)}KB"
            entry = _PreviewCacheEntry(
                image=image,
                msg=msg,
                width=target_size.width(),
                height=target_size.height(),
                bytes_size=max(image.sizeInBytes(), 0),
            )
            self._cache.put(key, entry)
            return [True, image, msg, target_size.width(), target_size.height()]
        except Exception:
            signal.show_log_text(traceback.format_exc())
            return _preview_placeholder(poster, "加载失败")


async def get_pixmap(pic_path: Path, poster=True, pic_from=""):
    try:
        # 使用 QImageReader 加载，适合加载大文件，pixmap适合显示
        # 判断是否可读取
        img = QImageReader(pic_path.as_posix())
        if img.canRead():
            img = img.read()
            pix = QPixmap(img)
            pic_width = img.size().width()
            pic_height = img.size().height()
            pic_file_size = int(await aiofiles.os.path.getsize(pic_path) / 1024)
            if pic_width and pic_height:
                if poster:
                    if pic_width / pic_height > 156 / 220:
                        w = 156
                        h = int(156 * pic_height / pic_width)
                    else:
                        w = int(220 * pic_width / pic_height)
                        h = 220
                else:
                    if pic_width / pic_height > 328 / 220:
                        w = 328
                        h = int(328 * pic_height / pic_width)
                    else:
                        w = int(220 * pic_width / pic_height)
                        h = 220
                msg = f"{pic_from.title()}: {pic_width}*{pic_height}/{pic_file_size}KB"
                return [True, pix, msg, w, h]
        await delete_file_async(pic_path)
        if poster:
            return [False, "", "封面图损坏", 156, 220]
        return [False, "", "缩略图损坏", 328, 220]
    except Exception:
        signal.show_log_text(traceback.format_exc())
        return [False, "", "加载失败", 156, 220]


def cut_pic(pic_path: Path):
    # 打开图片, 获取图片尺寸
    img = None
    img_new = None
    img_new_png = None
    try:
        img = Image.open(pic_path)  # 返回一个Image对象

        w, h = img.size
        prop = h / w

        # 判断裁剪方式
        if prop < 1.4:  # 胖，裁剪左右
            ax = int((w - h / 1.5) / 2)
            ay = 0
            bx = int(ax + h / 1.5)
            by = int(h)
        elif prop > 1.6:  # 瘦，裁剪上下
            ax = 0
            ay = int((h - 1.5 * w) / 2)
            bx = int(w)
            by = int(h - ay)
        else:
            img.close()
            return

        # 裁剪并保存
        img_new = img.convert("RGB")
        img_new_png = img_new.crop((ax, ay, bx, by))
        img_new_png.save(pic_path, quality=95, subsampling=0)
    except Exception:
        signal.show_traceback_log(traceback.format_exc())
        signal.show_log_text(traceback.format_exc())
    finally:
        if img_new_png:
            img_new_png.close()
        if img_new:
            img_new.close()
        if img:
            img.close()


async def fix_pic_async(pic_path: Path, new_path: Path):
    await asyncio.to_thread(fix_pic, pic_path, new_path)


def fix_pic(pic_path: Path, new_path: Path):
    pic = None
    fixed_pic = None
    try:
        pic = Image.open(pic_path)
        (w, h) = pic.size
        prop = w / h
        if prop < 1.156:  # 左右居中
            backdrop_w = int(1.156 * h)  # 背景宽度
            backdrop_h = int(h)  # 背景宽度
            foreground_x = int((backdrop_w - w) / 2)  # 前景x点
            foreground_y = 0  # 前景y点
        else:  # 下面对齐
            ax, ay, bx, by = int(w * 0.0155), int(h * 0.0888), int(w * 0.9833), int(h * 0.9955)
            pic_new = pic.convert("RGB")
            pic = pic_new.crop((ax, ay, bx, by))
            backdrop_w = bx - ax
            backdrop_h = int((bx - ax) / 1.156)
            foreground_x = 0
            foreground_y = int(backdrop_h - (by - ay))
        fixed_pic = pic.resize((backdrop_w, backdrop_h))  # 背景拉伸
        fixed_pic = fixed_pic.filter(ImageFilter.GaussianBlur(radius=50))  # 背景高斯模糊
        fixed_pic.paste(pic, (foreground_x, foreground_y))  # 粘贴原图
        fixed_pic = fixed_pic.convert("RGB")
        fixed_pic.save(new_path, quality=95, subsampling=0)
    except Exception:
        signal.show_log_text(f"{traceback.format_exc()}\n Pic: {pic_path}")
        signal.show_traceback_log(traceback.format_exc())
    finally:
        if pic is not None:
            pic.close()
        if fixed_pic is not None:
            fixed_pic.close()
