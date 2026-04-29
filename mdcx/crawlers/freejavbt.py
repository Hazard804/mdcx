#!/usr/bin/env python3

import re
from typing import override

from lxml import etree
from lxml.html import soupparser

from ..base.web import get_dmm_trailer
from ..config.models import Website
from .base import BaseCrawler, Context, CralwerException, CrawlerData


def get_title(html):
    try:
        # 2025-07-05 number和title之间有竖线可能是以前的格式？目前看是没有的，一般是`ABC-123 xxx | FREE JAV BT` 这种格式
        raw = html.xpath("//title/text()")[0]
        raw = raw.replace("| FREE JAV BT", "")
        result = raw.split("|")
        if len(result) == 2:
            number = result[0].strip()
            title = " ".join(result[1:]).replace(number, "").strip()
        else:
            result = raw.split(" ")
            if len(result) > 2:
                number = result[0].strip()
                title = " ".join(result[1:]).strip()

        title = (
            title.replace("中文字幕", "")
            .replace("無碼", "")
            .replace("\\n", "")
            .replace("_", "-")
            .replace(number.upper(), "")
            .replace(number, "")
            .replace("--", "-")
            .strip()
        )
        if not title or "翻译错误" in title or "每日更新" in str(result):
            return "", ""
        return title, number
    except Exception:
        return "", ""


def get_actor(html):
    actor_result = html.xpath('//a[contains(concat(" ", normalize-space(@class), " "), " actress ")]/text()')
    av_man = [
        "貞松大輔",
        "鮫島",
        "森林原人",
        "黒田悠斗",
        "主観",
        "吉村卓",
        "野島誠",
        "小田切ジュン",
        "しみけん",
        "セツネヒデユキ",
        "大島丈",
        "玉木玲",
        "ウルフ田中",
        "ジャイアント廣田",
        "イセドン内村",
        "西島雄介",
        "平田司",
        "杉浦ボッ樹",
        "大沢真司",
        "ピエール剣",
        "羽田",
        "田淵正浩",
        "タツ",
        "南佳也",
        "吉野篤史",
        "今井勇太",
        "マッスル澤野",
        "井口",
        "松山伸也",
        "花岡じった",
        "佐川銀次",
        "およよ中野",
        "小沢とおる",
        "橋本誠吾",
        "阿部智広",
        "沢井亮",
        "武田大樹",
        "市川哲也",
        "???",
        "浅野あたる",
        "梅田吉雄",
        "阿川陽志",
        "素人",
        "結城結弦",
        "畑中哲也",
        "堀尾",
        "上田昌宏",
        "えりぐち",
        "市川潤",
        "沢木和也",
        "トニー大木",
        "横山大輔",
        "一条真斗",
        "真田京",
        "イタリアン高橋",
        "中田一平",
        "完全主観",
        "イェーイ高島",
        "山田万次郎",
        "澤地真人",
        "杉山",
        "ゴロー",
        "細田あつし",
        "藍井優太",
        "奥村友真",
        "ザーメン二郎",
        "桜井ちんたろう",
        "冴山トシキ",
        "久保田裕也",
        "戸川夏也",
        "北こうじ",
        "柏木純吉",
        "ゆうき",
        "トルティーヤ鈴木",
        "神けんたろう",
        "堀内ハジメ",
        "ナルシス小林",
        "アーミー",
        "池田径",
        "吉村文孝",
        "優生",
        "久道実",
        "一馬",
        "辻隼人",
        "片山邦生",
        "Qべぇ",
        "志良玉弾吾",
        "今岡爽紫郎",
        "工藤健太",
        "原口",
        "アベ",
        "染島貢",
        "岩下たろう",
        "小野晃",
        "たむらあゆむ",
        "川越将護",
        "桜木駿",
        "瀧口",
        "TJ本田",
        "園田",
        "宮崎",
        "鈴木一徹",
        "黒人",
        "カルロス",
        "天河",
        "ぷーてゃん",
        "左曲かおる",
        "富田",
        "TECH",
        "ムールかいせ",
        "健太",
        "山田裕二",
        "池沼ミキオ",
        "ウサミ",
        "押井敬之",
        "浅見草太",
        "ムータン",
        "フランクフルト林",
        "石橋豊彦",
        "矢野慎二",
        "芦田陽",
        "くりぼ",
        "ダイ",
        "ハッピー池田",
        "山形健",
        "忍野雅一",
        "渋谷優太",
        "服部義",
        "たこにゃん",
        "北山シロ",
        "つよぽん",
        "山本いくお",
        "学万次郎",
        "平井シンジ",
        "望月",
        "ゆーきゅん",
        "頭田光",
        "向理来",
        "かめじろう",
        "高橋しんと",
        "栗原良",
        "テツ神山",
        "タラオ",
        "真琴",
        "滝本",
        "金田たかお",
        "平ボンド",
        "春風ドギー",
        "桐島達也",
        "中堀健二",
        "徳田重男",
        "三浦屋助六",
        "志戸哲也",
        "ヒロシ",
        "オクレ",
        "羽目白武",
        "ジョニー岡本",
        "幸野賀一",
        "インフィニティ",
        "ジャック天野",
        "覆面",
        "安大吉",
        "井上亮太",
        "笹木良一",
        "艦長",
        "軍曹",
        "タッキー",
        "阿部ノボル",
        "ダウ兄",
        "まーくん",
        "梁井一",
        "カンパニー松尾",
        "大塚玉堂",
        "日比野達郎",
        "小梅",
        "ダイナマイト幸男",
        "タケル",
        "くるみ太郎",
        "山田伸夫",
        "氷崎健人",
    ]
    actor_list = [i.strip() for i in actor_result if i.replace("?", "")]
    all_actor_list = actor_list.copy()
    for each in all_actor_list:
        if each in av_man:
            actor_list.remove(each)
    actor = ",".join(actor_list)
    all_actor = ",".join(all_actor_list)
    actor = actor if "暫無" not in actor else ""
    all_actor = all_actor if "暫無" not in all_actor else ""
    return actor, all_actor


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_detail_html(html_info: str):
    html_detail = etree.fromstring(html_info, etree.HTMLParser())
    if html_detail is None:
        html_detail = soupparser.fromstring(html_info)
    return html_detail


def get_runtime(html):
    result = html.xpath(
        '//span[contains(text(), "时长") or contains(text(), "時長") or contains(text(), "収録時間")]/following-sibling::*//text()'
    )
    if result:
        result = re.findall(r"\d+", result[0])
    return result[0] if result else ""


def get_series(html):
    result = html.xpath('//span[contains(text(), "系列")]/following-sibling::*//text()')
    return "".join(result).strip() if result else ""


def get_director(html):
    result = html.xpath(
        '//span[contains(text(), "导演") or contains(text(), "導演") or contains(text(), "監督")]/following-sibling::*//text()'
    )
    return result[0] if result else ""


def get_studio(html):
    result = html.xpath(
        '//span[contains(text(), "制作") or contains(text(), "製作") or contains(text(), "メーカー")]/following-sibling::*//text()'
    )
    return result[0] if result else ""


def get_publisher(html):
    result = html.xpath('//span[contains(text(), "发行") or contains(text(), "發行")]/following-sibling::*//text()')
    return result[0] if result else ""


def get_release(html):
    result = html.xpath('//span[contains(text(), "日期") or contains(text(), "発売日")]/following-sibling::*//text()')
    return result[0] if result else ""


def get_year(release):
    result = re.findall(r"\d{4}", release)
    return result[0] if result else ""


def get_tag(html):
    result = html.xpath(
        '//a[contains(concat(" ", normalize-space(@class), " "), " genre ")]//text()'
        ' | //a[contains(@href, "/genre/") or contains(@href, "/genres/") or contains(@href, "/tag/")]//text()'
    )
    tag = ""
    for each in result:
        item = each.strip().lstrip("#").replace("，", "")
        if item:
            tag += item + ","
    return tag.strip(",")


def get_cover(html):
    result = html.xpath(
        "//img[contains(@class, 'video-cover')]/@data-src"
        " | //img[contains(@class, 'video-cover')]/@src"
        " | //meta[@property='og:image']/@content"
        " | //meta[@name='twitter:image']/@content"
        " | //img[contains(@class, 'lazyload') and contains(@data-src, '/samples/')]/@data-src"
    )
    for item in result:
        item = item.strip()
        if item and "no_preview_lg" not in item and item.startswith("http"):
            return item
    return ""


def get_extrafanart(html):  # 获取封面链接
    extrafanart_list = html.xpath("//a[@class='tile-item']/@href")
    if "#preview-video" in str(extrafanart_list):
        extrafanart_list.pop(0)
    return extrafanart_list


async def get_trailer(html):  # 获取预览片
    trailer_url_list = html.xpath("//video[@id='preview-video']/source/@src")
    return await get_dmm_trailer(trailer_url_list[0]) if trailer_url_list else ""


def get_mosaic(title, actor):
    title += actor
    mosaic = "无码" if "無碼" in title or "無修正" in title or "Uncensored" in title else ""
    return mosaic


class FreejavbtCrawler(BaseCrawler):
    @classmethod
    @override
    def site(cls) -> Website:
        return Website.FREEJAVBT

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://freejavbt.com"

    @override
    async def _run(self, ctx: Context):
        real_url = f"{self.base_url}/{ctx.input.number}"
        if ctx.input.appoint_url:
            real_url = ctx.input.appoint_url.replace("/zh/", "/").replace("/en/", "/").replace("/ja/", "/")
        ctx.debug(f"番号地址: {real_url}")
        ctx.debug_info.detail_urls = [real_url]

        html_info, error = await self.async_client.get_text(real_url)
        if html_info is None:
            raise CralwerException(f"请求错误: {error}")
        if not html_info:
            raise CralwerException("未匹配到番号！")

        html_detail = parse_detail_html(html_info)
        if html_detail is None:
            raise CralwerException("HTML 解析失败")

        title, number = get_title(html_detail)
        if not title or "single-video-info col-12" not in html_info:
            raise CralwerException("数据获取失败: 番号标题不存在！")

        actor, all_actor = get_actor(html_detail)
        release = get_release(html_detail)
        tag = get_tag(html_detail)
        director = get_director(html_detail)
        data = CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=split_csv(actor),
            all_actors=split_csv(all_actor),
            outline="",
            originalplot="",
            tags=split_csv(tag),
            release=release,
            year=get_year(release),
            runtime=get_runtime(html_detail),
            score="",
            series=get_series(html_detail),
            directors=split_csv(director),
            studio=get_studio(html_detail),
            publisher=get_publisher(html_detail),
            thumb=get_cover(html_detail),
            poster="",
            extrafanart=get_extrafanart(html_detail),
            trailer=await get_trailer(html_detail),
            image_download=False,
            image_cut="right",
            mosaic=get_mosaic(title, actor),
            external_id=real_url,
            wanted="",
        )
        result = data.to_result()
        result.source = self.site().value
        ctx.debug("数据获取成功！")
        return result

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        return None

    @override
    async def _parse_search_page(self, ctx: Context, html, search_url: str) -> list[str] | str | None:
        return None

    @override
    async def _parse_detail_page(self, ctx: Context, html, detail_url: str) -> CrawlerData | None:
        return None
