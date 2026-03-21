import asyncio
import concurrent
import concurrent.futures
import contextlib
import ctypes
import html
import inspect
import random
import re
import threading
import time
import traceback
import unicodedata
from collections.abc import Coroutine
from concurrent.futures import Future
from pathlib import Path
from threading import Thread
from typing import Any, TypeVar

from ..consts import IS_NFC
from ..manual import ManualConfig

T = TypeVar("T")


class AsyncBackgroundExecutor:
    """可重用的异步任务执行器, 将协程提交到运行于后台线程的事件循环中执行"""

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop
        self._pending_futures: set[Future] = set()
        self._lock = threading.Lock()
        self._running = False
        self._start_background_thread()

    def submit(self, coro: Coroutine[Any, Any, T]) -> Future[T]:
        """提交一个协程到后台线程执行, 返回一个 Future 对象. 此方法线程安全且非阻塞."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        future.add_done_callback(self._remove_future)
        with self._lock:
            self._pending_futures.add(future)
        return future

    def run(self, coro: Coroutine[Any, Any, T]) -> T:
        """submit 的阻塞版本, 等待协程执行完毕并返回结果. 此方法线程安全."""
        return self.submit(coro).result()

    def wait_all(self, timeout=None):
        """等待所有未完成任务执行完毕, 任务异常将作为结果返回. 此方法线程安全."""
        with self._lock:
            current_futures = list(self._pending_futures)
            if not current_futures:
                return []
        try:
            done, not_done = concurrent.futures.wait(
                current_futures,
                timeout=timeout,
                return_when=concurrent.futures.ALL_COMPLETED,
            )
            if not_done:
                raise TimeoutError(f"{len(not_done)} tasks not completed within timeout")
            results = []
            for future in done:
                try:
                    results.append(future.result())
                except Exception as e:
                    results.append(e)
            return results
        except Exception:
            for future in current_futures:
                if not future.done():
                    future.cancel()
            raise

    def cancel(self):
        """取消所有任务"""
        with self._lock:
            if not self._running:
                return
            self._running = False
            _pending_futures = list(self._pending_futures)

        # 取消所有待处理的任务
        for future in _pending_futures:
            if not future.done():
                future.cancel()  # 此处会运行 callback _remove_future
        self._running = True  # 此方法不关闭后台线程和事件循环, 仅取消任务

    def cancel_async(self):
        """取消所有任务. cancel 的非阻塞版本

        提交一个新的任务到事件循环中去取消其他任务
        """
        with self._lock:
            if not self._running:
                return
            _pending_futures = list(self._pending_futures)
            if not _pending_futures:
                return

        # 创建一个异步任务来取消所有待处理任务
        async def _cancel_all():
            for future in _pending_futures:
                if not future.done():
                    future.cancel()
            return True

        # 提交取消任务到事件循环
        return self.submit(_cancel_all())

    def _run_event_loop(self):
        """运行事件循环的线程函数"""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop_started.set()
            self._loop.run_forever()
        except Exception:
            # 如果启动失败，设置事件以避免主线程永远等待
            self._loop_started.set()
            # 不重新抛出异常，让线程正常结束
        finally:
            # 清理资源
            if self._loop and not self._loop.is_closed():
                with contextlib.suppress(Exception):
                    self._loop.close()
            # 重置loop引用
            self._loop = None  # type: ignore

    def _remove_future(self, future):
        """自动移除已完成的任务"""
        with self._lock:
            self._pending_futures.discard(future)

    def _start_background_thread(self):
        self._loop_started = threading.Event()
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True, name="AsyncBackgroundThread")
        self._thread.start()
        self._running = True
        # 等待事件循环启动
        if not self._loop_started.wait(timeout=10.0):
            raise RuntimeError("Failed to start background event loop within 10 seconds")

    def __del__(self):
        """析构函数，确保资源被释放"""
        try:
            self.cancel()
            self._loop.stop()
            self._thread.join(timeout=5.0)
        except Exception:
            pass  # 忽略析构时的异常


executor = AsyncBackgroundExecutor()  # 全局执行器
_INLINE_SCRIPT_SPLIT_RE = re.compile(r'"\]\)\s*</script>\s*<script>\s*self\.__next_f\.push\(\[\d+,\s*"', re.IGNORECASE)
_TEXT_URL_RE = re.compile(r'(?<!["\'=])(https?://[^\s"\'<>]+)', re.IGNORECASE)


def get_current_time() -> str:
    return time.strftime("%H:%M:%S", time.localtime())


def get_used_time(start_time: float) -> float:
    return round((time.time() - start_time), 2)


def get_real_time(t) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t))


def collapse_inline_script_splits(text: str) -> str:
    return _INLINE_SCRIPT_SPLIT_RE.sub("", str(text or ""))


def add_html(text: str) -> str:
    # 先清理 URL 污染串（例如: https://a.com/...">https://a.com/...）
    text = re.sub(r'(?P<u>https?://[^\s"\'<>]+)\s*">+\s*(?P=u)', r"\g<u>", text)

    # 特殊字符转义
    text = re.sub(r'href="https?://', 'href="🔮🧿⚔️', text, flags=re.IGNORECASE)  # 例外不转换的

    # 替换纯文本链接为超链接（避免替换 HTML 属性中的 URL）
    def _replace_url(match: re.Match[str]) -> str:
        each_url = match.group(1)
        safe_href = each_url.replace("&", "&amp;")
        return f'<a href="{safe_href}">{each_url}</a>'

    text = re.sub(r'(?<!["\'=])(https?://[^\s"\'<>]+)', _replace_url, text)
    text = text.replace('href="🔮🧿⚔️', 'href="https')  # 还原不转换的

    # 链接放在span里，避免点击后普通文本变超链接，设置样式为pre-wrap（保留空格换行）
    return f'<span style="white-space: pre-wrap;">{text}</span>'


def add_html_plain_text(text: str) -> str:
    text = str(text or "")
    parts: list[str] = []
    last_end = 0

    for match in _TEXT_URL_RE.finditer(text):
        parts.append(html.escape(text[last_end : match.start()]))
        each_url = match.group(1)
        safe_href = html.escape(each_url, quote=True).replace("&#x27;", "&#39;")
        parts.append(f'<a href="{safe_href}">{html.escape(each_url)}</a>')
        last_end = match.end()

    parts.append(html.escape(text[last_end:]))
    return f'<span style="white-space: pre-wrap;">{"".join(parts)}</span>'


def clean_list(a: str) -> str:
    """
    移除逗号分隔的字符串中的重复项, 同时移除每项首尾的空格, 并保持顺序.
    """
    return ",".join(dict.fromkeys(w.strip() for w in a.split(",") if w.strip()).keys())


# todo 此方法调用 c api 强制终止线程, 在异步版本中应该不需要
def _async_raise(tid, exctype):
    """raises the exception, performs cleanup if needed"""
    tid = ctypes.c_long(tid)
    if not inspect.isclass(exctype):
        exctype = type(exctype)
    res = 1
    while res == 1:
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, ctypes.py_object(exctype))
    if res == 0:
        # raise ValueError("invalid thread id")
        pass
    elif res != 1:
        # """if it returns a number greater than one, you're in trouble,
        # and you should call it again with exc=NULL to revert the effect"""
        ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, None)
        raise SystemError("PyThreadState_SetAsyncExc failed")


# todo 同上, 应该优雅的退出线程
def kill_a_thread(t: Thread):
    try:
        while t.is_alive():
            _async_raise(t.ident, SystemExit)
    except Exception:
        print(traceback.format_exc())
        _async_raise(t.ident, SystemExit)


def get_random_headers() -> dict:
    """
    随机生成复杂的HTTP headers
    包括随机的User-Agent、Accept、Accept-Language等字段
    字段的存在与否和具体值都会随机变化
    """

    # 各种浏览器的User-Agent池
    user_agents = [
        # Chrome Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{}.0.{}.{} Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{}.0.{}.{} Safari/537.36",
        # Chrome Mac
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{}.0.{}.{} Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{}.0.{}.{} Safari/537.36",
        # Firefox Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{}.0) Gecko/20100101 Firefox/{}.0",
        "Mozilla/5.0 (Windows NT 10.0; WOW64; rv:{}.0) Gecko/20100101 Firefox/{}.0",
        # Firefox Mac
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:{}.0) Gecko/20100101 Firefox/{}.0",
        # Safari Mac
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.{}.{} Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.{}.{} Safari/605.1.15",
        # Edge
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{}.0.{}.{} Safari/537.36 Edg/{}.0.{}.{}",
        # Mobile Chrome
        "Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{}.0.{}.{} Mobile Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1",
    ]

    # 生成随机版本号
    def get_chrome_version():
        major = random.randint(100, 130)
        minor = random.randint(0, 5)
        build = random.randint(1000, 9999)
        patch = random.randint(100, 999)
        return major, minor, build, patch

    def get_firefox_version():
        version = random.randint(90, 120)
        return version, version

    def get_safari_version():
        major = random.randint(14, 17)
        minor = random.randint(0, 9)
        patch = random.randint(0, 9)
        return major, minor, patch

    # 随机选择User-Agent模板并填充版本号
    ua_template = random.choice(user_agents)

    if "Chrome" in ua_template and "Firefox" not in ua_template:
        if "Edg" in ua_template:
            # Edge浏览器
            chrome_ver = get_chrome_version()
            edge_ver = get_chrome_version()
            ua = ua_template.format(*chrome_ver, *edge_ver)
        else:
            # Chrome浏览器
            chrome_ver = get_chrome_version()
            ua = ua_template.format(*chrome_ver)
    elif "Firefox" in ua_template:
        # Firefox浏览器
        ff_ver = get_firefox_version()
        ua = ua_template.format(*ff_ver)
    elif "Safari" in ua_template and "Chrome" not in ua_template:
        # Safari浏览器
        safari_ver = get_safari_version()
        ua = ua_template.format(*safari_ver)
    else:
        ua = ua_template

    # 基础headers
    headers = {"User-Agent": ua}

    # Accept字段选项
    accept_options = [
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "application/json,text/plain,*/*",
        "*/*",
    ]

    # Accept-Language字段选项
    accept_language_options = [
        "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7",
        "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "zh-CN,zh;q=0.9",
        "en-US,en;q=0.9",
        "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        "en-US,en;q=0.5",
    ]

    # Accept-Encoding字段选项
    accept_encoding_options = ["gzip, deflate, br", "gzip, deflate", "gzip, deflate, br, zstd", "identity"]

    # Connection字段选项
    connection_options = ["keep-alive", "close"]

    # Cache-Control字段选项
    cache_control_options = ["no-cache", "max-age=0", "no-store", "must-revalidate"]

    # Sec-Fetch系列字段选项
    sec_fetch_dest_options = ["document", "empty", "image", "script", "style"]
    sec_fetch_mode_options = ["navigate", "cors", "no-cors", "same-origin"]
    sec_fetch_site_options = ["none", "same-origin", "same-site", "cross-site"]

    # 随机添加可选字段（每个字段都有一定概率被包含）
    optional_headers = [
        ("Accept", accept_options, 0.8),
        ("Accept-Language", accept_language_options, 0.9),
        ("Accept-Encoding", accept_encoding_options, 0.7),
        ("Connection", connection_options, 0.6),
        ("DNT", ["1"], 0.3),
        ("Upgrade-Insecure-Requests", ["1"], 0.5),
        ("Cache-Control", cache_control_options, 0.4),
        ("Pragma", ["no-cache"], 0.2),
        ("Sec-Fetch-Dest", sec_fetch_dest_options, 0.4),
        ("Sec-Fetch-Mode", sec_fetch_mode_options, 0.4),
        ("Sec-Fetch-Site", sec_fetch_site_options, 0.4),
        ("Sec-Fetch-User", ["?1"], 0.3),
        ("Sec-CH-UA", ['"Google Chrome";v="130", "Chromium";v="130", "Not?A_Brand";v="99"'], 0.3),
        ("Sec-CH-UA-Mobile", ["?0"], 0.3),
        ("Sec-CH-UA-Platform", ['"Windows"', '"macOS"', '"Linux"'], 0.3),
    ]

    # 随机添加字段
    for header_name, options, probability in optional_headers:
        if random.random() < probability:
            headers[header_name] = random.choice(options)

    # 随机添加一些自定义字段
    custom_headers = [
        ("X-Requested-With", ["XMLHttpRequest"], 0.2),
        ("Origin", ["https://www.google.com", "https://www.bing.com"], 0.1),
        ("Referer", ["https://www.google.com/", "https://www.bing.com/"], 0.3),
        (
            "X-Forwarded-For",
            [f"{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}"],
            0.1,
        ),
    ]

    for header_name, options, probability in custom_headers:
        if random.random() < probability:
            if header_name == "X-Forwarded-For":
                # 生成随机IP
                ip = f"{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}"
                headers[header_name] = ip
            else:
                headers[header_name] = random.choice(options)

    return headers


def singleton(cls):
    _instance = {}

    def inner():
        if cls not in _instance:
            _instance[cls] = cls()
        return _instance[cls]

    return inner


def nfd2c(path: str) -> str:
    # 转换 NFC(mac nfc和nfd都能访问到文件，但是显示的是nfd，这里统一使用nfc，避免各种问题。
    # 日文浊音转换（mac的坑，osx10.12以下使用nfd，以上兼容nfc和nfd，只是显示成了nfd）
    return unicodedata.normalize("NFC", path) if IS_NFC else unicodedata.normalize("NFD", path)


def split_path(path: str | Path) -> tuple[Path, str]:
    path = Path(path)
    return path.parent, path.name


def get_new_release(release: str, release_rule: str) -> str:
    if not release:
        release = "0000-00-00"
    if release_rule == "YYYY-MM-DD":
        return release
    year, month, day = re.findall(r"(\d{4})-(\d{2})-(\d{2})", release)[0]
    return release_rule.replace("YYYY", year).replace("YY", year[-2:]).replace("MM", month).replace("DD", day)


def convert_half(string: str) -> str:
    # 替换敏感词
    for key, value in ManualConfig.SPECIAL_WORD.items():
        string = string.replace(key, value)
    # 替换全角为半角
    for each in ManualConfig.FULL_HALF_CHAR:
        string = string.replace(each[0], each[1])
    # 去除空格等符号
    return re.sub(r"[\W_]", "", string).upper()
