from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config.models import Config


class BrowserProvider:
    def __init__(self, config: "Config"):
        self.config = config

    async def get_browser(self) -> Any:
        raise RuntimeError("当前版本已移除浏览器请求模式")

    async def close(self):
        return None
