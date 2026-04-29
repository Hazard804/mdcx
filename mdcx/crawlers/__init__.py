from ..config.models import Website
from . import (
    avbase_new,
    avsex,
    avsox,
    cableav,
    cnmdb,
    dahlia,
    faleno,
    fantastica,
    giga,
    hscangku,
    jav321,
    javday,
    javdbapi,
    kin8,
    love6,
    lulubar,
    madouqu,
    mdtv,
    mgstage,
    missav,
    mmtv,
    xcity,
)
from .airav_cc import AiravCcCrawler
from .avbase_new import AvbaseCrawler
from .avsex import AvsexCrawler
from .avsox import AvsoxCrawler
from .base import get_crawler, get_registered_crawler_sites, register_crawler
from .base.compat import get_v1_crawler
from .cableav import CableavCrawler
from .cnmdb import CnmdbCrawler
from .dahlia import DahliaCrawler
from .dmm_new import DmmCrawler
from .faleno import FalenoCrawler
from .fantastica import FantasticaCrawler
from .fc2 import Fc2Crawler
from .fc2club import Fc2clubCrawler
from .fc2hub import Fc2hubCrawler
from .fc2ppvdb import Fc2ppvdbCrawler
from .freejavbt import FreejavbtCrawler
from .getchu import GetchuCrawler
from .getchu_dmm import GetchuDmmCrawler
from .giga import GigaCrawler
from .hdouban import HdoubanCrawler
from .hscangku import HscangkuCrawler
from .iqqtv import IqqtvCrawler
from .jav321 import Jav321Crawler
from .javbus import JavbusCrawler
from .javday import JavdayCrawler
from .javdb_new import JavdbCrawler
from .javlibrary import JavlibraryCrawler
from .kin8 import Kin8Crawler
from .love6 import Love6Crawler
from .lulubar import LulubarCrawler
from .madouqu import MadouquCrawler
from .mdtv import MdtvCrawler
from .mgstage import MgstageCrawler
from .mmtv import MmtvCrawler
from .mywife import MywifeCrawler
from .official import OfficialCrawler
from .prestige import PrestigeCrawler
from .theporndb import TheporndbCrawler
from .xcity import XcityCrawler

register_crawler(DmmCrawler)
register_crawler(JavdbCrawler)
register_crawler(javdbapi.JavdbApiCrawler)
register_crawler(AvbaseCrawler)
register_crawler(missav.MissavCrawler)
register_crawler(FalenoCrawler)
register_crawler(Jav321Crawler)
register_crawler(CableavCrawler)
register_crawler(MadouquCrawler)
register_crawler(MmtvCrawler)
register_crawler(DahliaCrawler)
register_crawler(FantasticaCrawler)
register_crawler(AvsoxCrawler)
register_crawler(CnmdbCrawler)
register_crawler(HscangkuCrawler)
register_crawler(Kin8Crawler)
register_crawler(Love6Crawler)
register_crawler(LulubarCrawler)
register_crawler(XcityCrawler)
register_crawler(GigaCrawler)
register_crawler(AvsexCrawler)
register_crawler(MdtvCrawler)
register_crawler(MgstageCrawler)
register_crawler(JavdayCrawler)
register_crawler(Fc2ppvdbCrawler)
register_crawler(PrestigeCrawler)
register_crawler(Fc2clubCrawler)
register_crawler(Fc2Crawler)
register_crawler(Fc2hubCrawler)
register_crawler(JavbusCrawler)
register_crawler(FreejavbtCrawler)
register_crawler(HdoubanCrawler)
register_crawler(IqqtvCrawler)
register_crawler(AiravCcCrawler)
register_crawler(GetchuCrawler)
register_crawler(GetchuDmmCrawler)
register_crawler(MywifeCrawler)
register_crawler(JavlibraryCrawler)
register_crawler(OfficialCrawler)
register_crawler(TheporndbCrawler)


def get_crawler_compat(site: Website):
    c = get_crawler(site)
    if c is not None:
        return c
    return get_v1_crawler(site)


def get_registered_crawler_site_values(*, include_hidden: bool = False) -> list[str]:
    """返回已注册刮削器的网站值, 用于 UI 动态填充."""
    return [site.value for site in get_registered_crawler_sites(include_hidden=include_hidden)]
