from fastapi import APIRouter
from pydantic import BaseModel, Field

from mdcx.crawlers import get_registered_crawler_sites
from mdcx.crawlers.base import get_crawler

router = APIRouter(prefix="/crawlers", tags=["刮削器"])


class CrawlerSiteInfo(BaseModel):
    value: str = Field(description="网站枚举值")
    label: str = Field(description="前端展示名称")
    base_url: str = Field(description="默认网站地址")
    registered: bool = Field(description="是否已注册刮削器")
    supports_custom_url: bool = Field(description="是否支持自定义网址")


@router.get("/sites", operation_id="getCrawlerSites", summary="获取已注册刮削器网站")
async def get_crawler_sites() -> list[CrawlerSiteInfo]:
    """返回运行时已注册的刮削器网站列表, 供前端动态枚举使用."""
    sites: list[CrawlerSiteInfo] = []
    for site in get_registered_crawler_sites():
        crawler_cls = get_crawler(site)
        if crawler_cls is None:
            continue
        sites.append(
            CrawlerSiteInfo(
                value=site.value,
                label=crawler_cls.display_name(),
                base_url=crawler_cls.base_url_(),
                registered=True,
                supports_custom_url=crawler_cls.supports_custom_url(),
            )
        )
    return sites
