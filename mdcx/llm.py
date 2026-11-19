import asyncio
import contextlib
import re
import threading
import time
from collections.abc import Callable
from enum import StrEnum

from aiolimiter import AsyncLimiter
from httpx import AsyncClient, Timeout, TimeoutException
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam


class LLMErrorKind(StrEnum):
    """LLM 请求失败的分类, 用于区分"只是慢"和"真的失败", 并决定是否可以重试."""

    TIMEOUT = "timeout"  # 超时: 可能只是模型较慢, 也可能是连接卡死
    AUTH = "auth"  # 鉴权失败: Key 无效或无权限, 重试无意义
    BAD_REQUEST = "bad_request"  # 请求被拒绝: 模型不存在/参数不支持/不支持流式等
    RATE_LIMIT = "rate_limit"  # 触发限流
    SERVER = "server"  # 服务端异常
    NETWORK = "network"  # 网络连接失败
    EMPTY = "empty"  # 请求成功但未返回有效内容
    UNKNOWN = "unknown"


# 这些分类属于"可能是瞬时问题", 值得重试
_RETRYABLE_KINDS = frozenset({LLMErrorKind.TIMEOUT, LLMErrorKind.RATE_LIMIT, LLMErrorKind.SERVER, LLMErrorKind.NETWORK})
# 流式请求命中这些分类时, 通常只是服务端不支持流式或流式响应不完整, 值得退回普通请求再试一次
# EMPTY 必须包含在内: 部分兼容接口在流式下只回 reason/usage 帧, 或丢弃 delta, 退回普通请求即可正常拿到正文
_STREAM_FALLBACK_KINDS = frozenset({LLMErrorKind.BAD_REQUEST, LLMErrorKind.UNKNOWN, LLMErrorKind.EMPTY})
# 明确指向"服务端不支持流式"的文案; 其余仅在错误描述里出现 stream 字样的错误不再误触发降级
_STREAM_UNSUPPORTED_HINTS = (
    "does not support stream",
    "doesn't support stream",
    "not support stream",
    "stream is not supported",
    "streaming is not supported",
    "stream not supported",
    "unsupported stream",
    "streaming is unsupported",
    "不支持流式",
    "流式输出不支持",
    "流式不支持",
)


class LLMError(Exception):
    """LLM 请求失败时抛出, 携带可分类的错误信息, 便于区分超时与真正的失败."""

    def __init__(
        self,
        kind: LLMErrorKind,
        detail: str = "",
        *,
        status: int | None = None,
        elapsed: float = 0.0,
        partial_chars: int = 0,
    ):
        super().__init__(detail or str(kind))
        self.kind = kind
        self.detail = detail.strip()
        self.status = status
        # 本次请求已耗时(秒), 用于说明"等了多久才失败"
        self.elapsed = elapsed
        # 流式请求中已接收到的正文字数, 用于说明"是否已经输出了一部分"
        self.partial_chars = partial_chars

    @property
    def retryable(self) -> bool:
        return self.kind in _RETRYABLE_KINDS

    @property
    def should_fallback_to_non_stream(self) -> bool:
        """是否值得退回普通(非流式)请求. 只在错误确实指向流式本身时成立.

        早期实现只判断错误描述里是否含 "stream", 导致超时/连接重置等普通错误也会
        触发降级并永久关闭流式; 这里改为按分类 + 明确文案判断, 避免误伤.
        """
        if self.kind in _STREAM_FALLBACK_KINDS:
            return True
        detail = self.detail.lower()
        return any(hint in detail for hint in _STREAM_UNSUPPORTED_HINTS)

    def message(self) -> str:
        """面向用户/日志的错误说明, 明确区分"慢"和"失败"."""
        if self.kind is LLMErrorKind.TIMEOUT:
            text = f"LLM 请求超时: 已等待 {self.elapsed:.0f}s 仍未完成"
            if self.partial_chars:
                text += f", 已接收 {self.partial_chars} 字但输出中断"
            return f"{text} (可能只是模型较慢, 可调大 LLM 读取超时)"
        if self.kind is LLMErrorKind.AUTH:
            return f"LLM 鉴权失败({self.status}): 请检查 API Key 与模型权限"
        if self.kind is LLMErrorKind.RATE_LIMIT:
            return f"LLM 触发限流({self.status}): {self.detail}" if self.detail else "LLM 触发限流"
        if self.kind is LLMErrorKind.NETWORK:
            return f"LLM 网络连接失败: {self.detail}" if self.detail else "LLM 网络连接失败"
        if self.kind is LLMErrorKind.SERVER:
            return f"LLM 服务端异常({self.status}): {self.detail}" if self.detail else "LLM 服务端异常"
        if self.kind is LLMErrorKind.BAD_REQUEST:
            return f"LLM 请求被拒绝({self.status}): {self.detail}" if self.detail else "LLM 请求被拒绝"
        if self.kind is LLMErrorKind.EMPTY:
            return f"LLM 未返回有效内容: {self.detail}" if self.detail else "LLM 未返回有效内容"
        return f"LLM 请求异常: {self.detail}" if self.detail else "LLM 请求异常"

    def brief(self) -> str:
        """单行摘要, 用于重试日志."""
        if self.kind is LLMErrorKind.TIMEOUT:
            text = f"LLM 请求超时(已等待 {self.elapsed:.0f}s)"
            if self.partial_chars:
                text += f", 已接收 {self.partial_chars} 字"
            return text
        return self.message()


def _exception_detail(exc: Exception) -> str:
    text = str(exc).strip().replace("\n", " ")
    return text[:200] if len(text) > 200 else text


def classify_llm_exception(exc: Exception, *, elapsed: float = 0.0, partial_chars: int = 0) -> LLMError:
    """将底层异常归类, 避免把"超时(可能只是慢)"和其他真正的失败混为一谈."""
    if isinstance(exc, LLMError):
        return exc
    detail = _exception_detail(exc)
    status = getattr(exc, "status_code", None)

    # 注意: APITimeoutError 是 APIConnectionError 的子类, 必须先判断超时
    if isinstance(exc, (APITimeoutError, TimeoutException)):
        return LLMError(LLMErrorKind.TIMEOUT, detail, elapsed=elapsed, partial_chars=partial_chars)
    if isinstance(exc, APIConnectionError):
        return LLMError(LLMErrorKind.NETWORK, detail, elapsed=elapsed, partial_chars=partial_chars)
    if isinstance(exc, APIStatusError):
        if status in (401, 403):
            kind = LLMErrorKind.AUTH
        elif status == 408:
            return LLMError(LLMErrorKind.TIMEOUT, detail, status=status, elapsed=elapsed, partial_chars=partial_chars)
        elif status == 429:
            kind = LLMErrorKind.RATE_LIMIT
        elif status is not None and status >= 500:
            kind = LLMErrorKind.SERVER
        else:
            kind = LLMErrorKind.BAD_REQUEST
        return LLMError(kind, detail, status=status, elapsed=elapsed, partial_chars=partial_chars)
    return LLMError(LLMErrorKind.UNKNOWN, detail, elapsed=elapsed, partial_chars=partial_chars)


def _clean_and_validate_text(text: str | None, *, elapsed: float, partial_chars: int) -> str:
    cleaned = text or ""
    # 移除 cot
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL)
    if not cleaned.strip():
        raise LLMError(
            LLMErrorKind.EMPTY,
            "模型返回内容为空",
            elapsed=elapsed,
            partial_chars=partial_chars,
        )
    return cleaned


class LLMClient:
    # 超时后额外放大超时的次数; 之后仍超时则按普通退避继续重试, 不再压缩 max_try 的尝试次数
    MAX_TIMEOUT_BOOST = 1
    # 非流式请求需要一次性覆盖整段生成耗时, 因此基准超时先放大
    NON_STREAM_TIMEOUT_FACTOR = 2.0
    # 流式输出期间的心跳日志间隔(秒), 便于确认"在输出"而不是"卡死"
    PROGRESS_LOG_INTERVAL = 30.0
    # 流式不可用后的降级冷却时间(秒); 过期后自动重新尝试流式, 避免一次异常永久关闭流式
    STREAM_FALLBACK_COOLDOWN = 600.0

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,  # https://api.openai.com/v1
        proxy: str | None = None,
        timeout: Timeout,
        rate: tuple[float, float],
    ):
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            # 关闭 SDK 内部重试, 统一由 ask() 按错误类型决定是否重试, 避免一次超时被放大成多次重发
            max_retries=0,
            http_client=AsyncClient(proxy=proxy, verify=False, timeout=timeout, follow_redirects=True),
            timeout=timeout,
        )
        # 保留基准超时配置, 重试时按倍数放大
        self._timeout = timeout
        self.limiter = AsyncLimiter(*rate)
        self._closed = False
        self._close_requested = False
        self._active_requests = 0
        self._active_lock = asyncio.Lock()
        self._lease_lock = threading.Lock()
        self._leases = 0
        # 服务端若不支持流式输出或流式响应不可用, 按模型记录降级截止时间, 到期后重新尝试流式
        self._stream_lock = threading.Lock()
        self._stream_disabled: dict[str, float] = {}

    def retain(self) -> None:
        with self._lease_lock:
            if self._closed:
                raise RuntimeError("LLM 客户端已关闭")
            self._leases += 1

    async def release(self) -> None:
        with self._lease_lock:
            if self._leases > 0:
                self._leases -= 1
        if self._close_requested:
            await self._close_if_idle()

    async def _begin_request(self) -> None:
        async with self._active_lock:
            if self._closed:
                raise RuntimeError("LLM 客户端已关闭")
            self._active_requests += 1

    async def _end_request(self) -> None:
        async with self._active_lock:
            self._active_requests = max(self._active_requests - 1, 0)

    async def _close_if_idle(self) -> bool:
        """无活跃请求且无租约时关闭客户端.

        与 retain() 共用 _lease_lock 做"判定空闲 + 标记关闭", 避免刚判定空闲就被新租约占用,
        进而导致新请求在 _begin_request 处撞上"客户端已关闭"。
        """
        if self._closed:
            return True
        async with self._active_lock:
            if self._active_requests > 0:
                return False
        with self._lease_lock:
            if self._closed:
                return True
            if self._leases > 0:
                return False
            # 必须在锁内先标记关闭, 使并发的 retain() 立即失败而不是拿到一个即将关闭的客户端
            self._closed = True
        self._close_requested = True
        with contextlib.suppress(Exception):
            await self.client.close()
        return True

    async def close_when_idle(self, *, poll_interval: float = 0.2) -> None:
        self._close_requested = True
        while not await self._close_if_idle():
            await asyncio.sleep(poll_interval)

    async def close(self) -> None:
        if self._closed:
            return
        self._close_requested = True
        self._closed = True
        with contextlib.suppress(Exception):
            await self.client.close()

    def _stream_enabled(self, model: str) -> bool:
        """该模型当前是否可以使用流式请求; 冷却期结束后自动恢复尝试."""
        now = time.monotonic()
        with self._stream_lock:
            disabled_until = self._stream_disabled.get(model)
            if disabled_until is None:
                return True
            if now < disabled_until:
                return False
            self._stream_disabled.pop(model, None)
            return True

    def _disable_stream(self, model: str) -> None:
        """临时降级该模型的流式请求, 冷却期后自动恢复, 避免一次异常永久关闭流式."""
        with self._stream_lock:
            self._stream_disabled[model] = time.monotonic() + self.STREAM_FALLBACK_COOLDOWN

    def _scale_timeout(self, factor: float) -> Timeout:
        base = self._timeout

        def scale(value: float | None) -> float | None:
            return None if value is None else value * factor

        return Timeout(
            connect=scale(base.connect),
            read=scale(base.read),
            write=scale(base.write),
            pool=scale(base.pool),
        )

    def _attempt_timeout(self, *, stream: bool, timeout_boost: int) -> Timeout | None:
        """按请求模式与超时放大次数计算本次请求的超时; 返回 None 表示沿用客户端默认值."""
        factor = 1.0
        if not stream:
            factor *= self.NON_STREAM_TIMEOUT_FACTOR
        if timeout_boost > 0:
            factor *= 2.0**timeout_boost
        if factor == 1.0:
            return None
        return self._scale_timeout(factor)

    async def _request_stream(
        self,
        kwargs: dict,
        *,
        started: float,
        partial: list[str],
        log_fn: Callable[[str], None],
    ) -> str:
        """流式请求: 超时判定变为"两个 chunk 之间的空闲时间", 因此慢但在输出的响应不会被判失败."""
        stream = await self.client.chat.completions.create(**kwargs, stream=True)
        next_progress_log = self.PROGRESS_LOG_INTERVAL
        try:
            async for chunk in stream:
                if not chunk.choices:
                    continue
                content = getattr(chunk.choices[0].delta, "content", None)
                if not content:
                    continue
                partial.append(content)
                elapsed = time.monotonic() - started
                if elapsed >= next_progress_log:
                    log_fn(f"🟡 LLM 仍在输出 (已等待 {elapsed:.0f}s, 已接收 {len(''.join(partial))} 字)")
                    next_progress_log = elapsed + self.PROGRESS_LOG_INTERVAL
        finally:
            with contextlib.suppress(Exception):
                await stream.close()
        text = "".join(partial)
        return _clean_and_validate_text(text, elapsed=time.monotonic() - started, partial_chars=len(text))

    async def _request(
        self,
        *,
        model: str,
        messages: list[ChatCompletionMessageParam],
        temperature: float,
        extra_body: object | None,
        stream: bool,
        timeout: Timeout | None,
        log_fn: Callable[[str], None],
    ) -> str:
        kwargs: dict = {"model": model, "messages": messages, "temperature": temperature}
        if extra_body is not None:
            kwargs["extra_body"] = extra_body
        if timeout is not None:
            kwargs["timeout"] = timeout

        started = time.monotonic()
        partial: list[str] = []
        try:
            if stream:
                return await self._request_stream(kwargs, started=started, partial=partial, log_fn=log_fn)
            chat = await self.client.chat.completions.create(**kwargs)
            text = chat.choices[0].message.content if chat.choices else None
        except Exception as e:
            raise classify_llm_exception(
                e,
                elapsed=time.monotonic() - started,
                partial_chars=len("".join(partial)),
            ) from e
        return _clean_and_validate_text(text, elapsed=time.monotonic() - started, partial_chars=0)

    async def ask(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.8,
        max_try: int,
        log_fn: Callable[[str], None] = lambda _: None,
        extra_body: object | None = None,
    ) -> str:
        """请求模型并返回正文; 失败时抛出 LLMError, 由调用方按错误类型决定后续处理."""
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        attempts = max(1, int(max_try))
        remaining = attempts
        attempt = 0
        wait = 1.0
        # 超时放大次数; 只影响本次请求使用的超时, 不占用 max_try 的尝试次数
        timeout_boost = 0
        stream = self._stream_enabled(model)

        try:
            await self._begin_request()
        except RuntimeError as err:
            # 客户端恰好在租约切换时被关闭, 转成统一错误说明, 便于上层按普通失败记录
            raise LLMError(LLMErrorKind.UNKNOWN, str(err)) from err
        try:
            while True:
                attempt += 1
                try:
                    # 限流只覆盖单次请求; 重试等待不占用信号量, 避免并发任务互相排队放大耗时
                    async with self.limiter:
                        return await self._request(
                            model=model,
                            messages=messages,
                            temperature=temperature,
                            extra_body=extra_body,
                            stream=stream,
                            timeout=self._attempt_timeout(stream=stream, timeout_boost=timeout_boost),
                            log_fn=log_fn,
                        )
                except LLMError as err:
                    # 流式不支持/流式响应为空或解析失败时, 退回普通请求再试, 不消耗重试次数
                    if stream and err.should_fallback_to_non_stream:
                        stream = False
                        attempt -= 1
                        self._disable_stream(model)
                        log_fn(f"🟡 LLM 流式请求不可用, 改用普通请求重试: {err.brief()}")
                        continue
                    remaining -= 1
                    if not err.retryable or remaining <= 0:
                        raise
                    if err.kind is LLMErrorKind.TIMEOUT and timeout_boost < self.MAX_TIMEOUT_BOOST:
                        # 首次超时优先加大超时; 后续仍超时则按普通退避继续重试, 不再压缩尝试次数
                        timeout_boost += 1
                        log_fn(f"⚠️ {err.brief()}, 加大超时后重试 ({attempt}/{attempts})")
                        continue
                    log_fn(f"⚠️ {err.brief()}, {wait:g}s 后重试 ({attempt}/{attempts})")
                    await asyncio.sleep(wait)
                    wait = min(wait * 2, 16)
        finally:
            await self._end_request()
