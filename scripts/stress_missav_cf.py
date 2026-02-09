import argparse
import asyncio
import random
import sys
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

from mdcx.web_async import AsyncWebClient


def safe_print(message: Any = "") -> None:
    text = str(message)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


@dataclass
class StressStats:
    total: int = 0
    success: int = 0
    failed: int = 0
    bypass_try_calls: int = 0
    bypass_try_force_refresh_calls: int = 0
    bypass_try_success: int = 0
    bypass_try_fail: int = 0
    bypass_cookie_calls: int = 0
    bypass_cookie_success: int = 0
    bypass_cookie_fail: int = 0
    bypass_cookie_with_cf_clearance: int = 0
    bypass_cookie_with_user_agent: int = 0
    bypass_cookie_cookie_only: int = 0
    cf_challenge_logs: int = 0
    cf_reuse_logs: int = 0
    cf_force_refresh_logs: int = 0
    latencies: list[float] = field(default_factory=list)
    errors: Counter[str] = field(default_factory=Counter)
    status_codes: Counter[int] = field(default_factory=Counter)
    applied_tokens: Counter[str] = field(default_factory=Counter)
    recent_logs: deque[str] = field(default_factory=lambda: deque(maxlen=100))


class StressLogger:
    def __init__(self, stats: StressStats, *, verbose: bool):
        self.stats = stats
        self.verbose = verbose

    def __call__(self, message: str) -> None:
        text = str(message)
        self.stats.recent_logs.append(text)
        if "检测到 Cloudflare 挑战页" in text:
            self.stats.cf_challenge_logs += 1
        if "复用最近刷新的 bypass cookies" in text:
            self.stats.cf_reuse_logs += 1
        if "强制刷新 bypass cookies" in text or "使用强刷模式请求 bypass cookies" in text:
            self.stats.cf_force_refresh_logs += 1
        if self.verbose:
            now = time.strftime("%H:%M:%S")
            safe_print(f"{now} {text}")


def build_urls(*, base_url: str, prefix: str, start: int, count: int, rounds: int, shuffle: bool) -> list[str]:
    all_urls: list[str] = []
    for _ in range(rounds):
        batch = [f"{base_url}/{prefix}-{num:03d}/cn" for num in range(start, start + count)]
        if shuffle:
            random.shuffle(batch)
        all_urls.extend(batch)
    return all_urls


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="并发模拟 MissAV 访问并统计 Cloudflare bypass 效果")
    parser.add_argument("--bypass-url", default="http://127.0.0.1:8000", help="bypass 服务地址")
    parser.add_argument("--proxy", default="", help="HTTP/SOCKS 代理地址，例如 http://127.0.0.1:7897")
    parser.add_argument("--base-url", default="https://missav.ws", help="MissAV 基础地址")
    parser.add_argument("--prefix", default="SNOS", help="番号前缀")
    parser.add_argument("--start", type=int, default=1, help="起始序号")
    parser.add_argument("--count", type=int, default=30, help="每轮请求数量")
    parser.add_argument("--rounds", type=int, default=2, help="轮次")
    parser.add_argument("--concurrency", type=int, default=20, help="并发数")
    parser.add_argument("--timeout", type=float, default=20.0, help="请求超时")
    parser.add_argument("--retry", type=int, default=5, help="请求重试次数")
    parser.add_argument("--shuffle", action="store_true", help="每轮随机打乱请求顺序")
    parser.add_argument("--fixed-url", default="", help="固定请求 URL（用于高频压测单链接）")
    parser.add_argument("--append-rand-query", action="store_true", help="请求时附加随机 query，降低缓存影响")
    parser.add_argument("--use-proxy", action="store_true", help="请求是否使用代理")
    parser.add_argument("--verbose", action="store_true", help="输出完整请求日志")
    return parser.parse_args()


async def run_once(args: argparse.Namespace) -> StressStats:
    stats = StressStats()
    logger = StressLogger(stats, verbose=args.verbose)
    client = AsyncWebClient(
        timeout=args.timeout,
        retry=args.retry,
        cf_bypass_url=args.bypass_url,
        proxy=args.proxy.strip() or None,
        log_fn=logger,
    )

    original_try_bypass = client._try_bypass_cloudflare
    original_call_bypass = client._call_bypass_cookies
    original_apply_binding = client._apply_cf_host_binding

    async def wrapped_try_bypass(*, host: str, target_url: str, use_proxy: bool, force_refresh: bool = False):
        stats.bypass_try_calls += 1
        if force_refresh:
            stats.bypass_try_force_refresh_calls += 1
        cookies, user_agent, error = await original_try_bypass(
            host=host,
            target_url=target_url,
            use_proxy=use_proxy,
            force_refresh=force_refresh,
        )
        if cookies:
            stats.bypass_try_success += 1
        else:
            stats.bypass_try_fail += 1
        return cookies, user_agent, error

    async def wrapped_call_bypass(target_url: str, *, force_refresh: bool, use_proxy: bool):
        stats.bypass_cookie_calls += 1
        cookies, user_agent, error = await original_call_bypass(
            target_url,
            force_refresh=force_refresh,
            use_proxy=use_proxy,
        )
        if error:
            stats.bypass_cookie_fail += 1
        else:
            stats.bypass_cookie_success += 1
        has_cf = bool(cookies.get("cf_clearance"))
        has_ua = bool((user_agent or "").strip())
        if has_cf:
            stats.bypass_cookie_with_cf_clearance += 1
        if has_ua:
            stats.bypass_cookie_with_user_agent += 1
        if has_cf and not has_ua:
            stats.bypass_cookie_cookie_only += 1
        return cookies, user_agent, error

    def wrapped_apply_binding(host: str, cookies: dict[str, str], user_agent: str) -> str:
        token = str(cookies.get("cf_clearance", "")).strip()
        if token:
            stats.applied_tokens[token] += 1
        return original_apply_binding(host, cookies, user_agent)

    client._try_bypass_cloudflare = wrapped_try_bypass  # type: ignore[method-assign]
    client._call_bypass_cookies = wrapped_call_bypass  # type: ignore[method-assign]
    client._apply_cf_host_binding = wrapped_apply_binding  # type: ignore[method-assign]

    if args.fixed_url.strip():
        fixed_url = args.fixed_url.strip()
        total = max(args.count, 1) * max(args.rounds, 1)
        urls = [fixed_url for _ in range(total)]
    else:
        urls = build_urls(
            base_url=args.base_url.rstrip("/"),
            prefix=args.prefix.strip().upper(),
            start=max(args.start, 1),
            count=max(args.count, 1),
            rounds=max(args.rounds, 1),
            shuffle=args.shuffle,
        )

    semaphore = asyncio.Semaphore(max(args.concurrency, 1))

    effective_use_proxy = bool(args.proxy.strip()) or args.use_proxy

    async def fetch(url: str) -> None:
        async with semaphore:
            request_url = url
            if args.append_rand_query:
                sep = "&" if "?" in request_url else "?"
                request_url = f"{request_url}{sep}_stress={time.time_ns()}"
            begin = time.perf_counter()
            response, error = await client.request("GET", request_url, use_proxy=effective_use_proxy)
            elapsed = time.perf_counter() - begin
            stats.latencies.append(elapsed)
            stats.total += 1
            if response is None:
                stats.failed += 1
                stats.errors[error or "未知错误"] += 1
                return
            stats.success += 1
            stats.status_codes[response.status_code] += 1

    await asyncio.gather(*(fetch(url) for url in urls))

    close_coro = getattr(client.curl_session, "close", None)
    if callable(close_coro):
        maybe = close_coro()
        if asyncio.iscoroutine(maybe):
            await maybe

    return stats


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * ratio))))
    return ordered[index]


def print_summary(args: argparse.Namespace, stats: StressStats, elapsed: float) -> None:
    effective_use_proxy = bool(args.proxy.strip()) or args.use_proxy
    qps = (stats.total / elapsed) if elapsed > 0 else 0.0
    success_rate = (stats.success / stats.total * 100) if stats.total else 0.0
    p50 = percentile(stats.latencies, 0.50)
    p90 = percentile(stats.latencies, 0.90)
    p99 = percentile(stats.latencies, 0.99)

    safe_print("=" * 72)
    safe_print("MissAV 并发过盾模拟结果")
    safe_print("=" * 72)
    safe_print(
        f"bypass={args.bypass_url}  proxy={args.proxy or 'none'}  use_proxy={effective_use_proxy}  concurrency={args.concurrency}  count={args.count}  rounds={args.rounds}  retry={args.retry}"
    )
    safe_print(
        f"total={stats.total}  success={stats.success}  failed={stats.failed}  success_rate={success_rate:.2f}%  elapsed={elapsed:.2f}s  qps={qps:.2f}"
    )
    safe_print(f"latency(s): p50={p50:.2f}  p90={p90:.2f}  p99={p99:.2f}")
    safe_print(
        "cf: "
        f"challenge_logs={stats.cf_challenge_logs}  reuse_logs={stats.cf_reuse_logs}  force_refresh_logs={stats.cf_force_refresh_logs}"
    )
    safe_print(
        "bypass_try: "
        f"calls={stats.bypass_try_calls}  force_refresh_calls={stats.bypass_try_force_refresh_calls}  "
        f"success={stats.bypass_try_success}  fail={stats.bypass_try_fail}"
    )
    safe_print(
        "bypass_cookie: "
        f"calls={stats.bypass_cookie_calls}  success={stats.bypass_cookie_success}  fail={stats.bypass_cookie_fail}  "
        f"with_cf_clearance={stats.bypass_cookie_with_cf_clearance}  with_ua={stats.bypass_cookie_with_user_agent}  "
        f"cookie_only={stats.bypass_cookie_cookie_only}"
    )

    if stats.applied_tokens:
        safe_print("applied_tokens(top5):")
        for token, count in stats.applied_tokens.most_common(5):
            safe_print(f"  - {token[:28]}... : {count}")

    if stats.errors:
        safe_print("errors(top5):")
        for error, count in stats.errors.most_common(5):
            safe_print(f"  - {count}x {error}")

    if stats.status_codes:
        safe_print("status_codes:")
        for code, count in sorted(stats.status_codes.items()):
            safe_print(f"  - {code}: {count}")

    if stats.recent_logs:
        safe_print("recent_logs(last10):")
        for line in list(stats.recent_logs)[-10:]:
            safe_print(f"  - {line}")


async def async_main() -> None:
    args = parse_args()
    start = time.perf_counter()
    stats = await run_once(args)
    elapsed = time.perf_counter() - start
    print_summary(args, stats, elapsed)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
