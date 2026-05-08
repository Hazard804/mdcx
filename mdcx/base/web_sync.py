from concurrent.futures import CancelledError

from ..config.manager import manager
from ..utils import executor


def get_text_sync(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    use_proxy=True,
    encoding: str = "utf-8",
):
    try:
        with manager.acquire_computed() as computed:
            return executor.run(
                computed.async_client.get_text(
                    url, headers=headers, cookies=cookies, encoding=encoding, use_proxy=use_proxy
                )
            )
    except CancelledError:
        return None, "任务已取消"


def get_json_sync(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    use_proxy=True,
):
    try:
        with manager.acquire_computed() as computed:
            return executor.run(
                computed.async_client.get_json(url, headers=headers, cookies=cookies, use_proxy=use_proxy)
            )
    except CancelledError:
        return None, "任务已取消"
