from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse

import requests


TIMEOUT = 25
AGE_PAGE_FLAG = "年齢認証 - FANZA"


@dataclass
class TrailerResult:
    detail_url: str
    trailer_url: str
    source: str


def decode_escaped_url(value: str) -> str:
    return value.encode("utf-8").decode("unicode_escape")


def with_https(url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    return url


def canonicalize_detail_url(detail_url: str) -> str:
    parsed = urlparse(detail_url)
    query_items = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not k.startswith("i3_")]
    cleaned = parsed._replace(query=urlencode(query_items, doseq=True), fragment="")
    normalized = urlunparse(cleaned)
    return normalized[:-1] if normalized.endswith("?") else normalized


def ensure_age_verified(session: requests.Session, target_url: str) -> None:
    age_url = "https://www.dmm.co.jp/age_check/=/declared=yes/?rurl=" + quote(target_url, safe="")
    session.get(age_url, timeout=TIMEOUT)


def fetch_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def normalize_number(raw_number: str) -> tuple[str, str, str]:
    number = raw_number.strip().lower()
    if matched := re.findall(r"[A-Za-z]+-?(\d+)", number):
        digits = matched[0]
        if len(digits) >= 5 and digits.startswith("00"):
            number = number.replace(digits, digits[2:])
        elif len(digits) == 4:
            number = number.replace("-", "0")
    number_00 = number.replace("-", "00")
    number_no_00 = number.replace("-", "")
    return number, number_00, number_no_00


def build_search_urls(number_00: str, number_no_00: str) -> list[str]:
    return [
        f"https://www.dmm.co.jp/search/=/searchstr={number_00}/sort=ranking/",
        f"https://www.dmm.co.jp/search/=/searchstr={number_no_00}/sort=ranking/",
        f"https://www.dmm.com/search/=/searchstr={number_no_00}/sort=ranking/",
    ]


def parse_search_detail_urls(search_html: str, raw_number: str) -> list[str]:
    matched_urls = set(re.findall(r'detailUrl\\":\\"(.*?)\\"', search_html))
    if not matched_urls:
        return []

    number_parts: re.Match[str] | None = re.search(r"(\d*[a-z]+)?-?(\d+)", raw_number.lower())
    if not number_parts:
        return [decode_escaped_url(each) for each in sorted(matched_urls)]

    prefix = number_parts.group(1) or ""
    digits = number_parts.group(2)
    n1 = f"{prefix}{digits:0>5}"
    n2 = f"{prefix}{digits}"

    result: list[str] = []
    for url in sorted(matched_urls):
        normalized = decode_escaped_url(url)
        normalized_lower = normalized.lower()
        if re.search(rf"[^a-z]{re.escape(n1)}[^0-9]", normalized_lower) or re.search(
            rf"[^a-z]{re.escape(n2)}[^0-9]", normalized_lower
        ):
            result.append(normalized)
    return result


def parse_search_sample_map(search_html: str) -> dict[str, str]:
    result: dict[str, str] = {}
    pattern = r'detailUrl\\":\\"(.*?)\\",\\"sampleUrl\\":\\"(.*?)\\"'
    for detail_raw, sample_raw in re.findall(pattern, search_html):
        detail_url = decode_escaped_url(detail_raw)
        sample_url = decode_escaped_url(sample_raw)
        if sample_url:
            result[detail_url] = with_https(sample_url)
    return result


def extract_video_url_from_ga_event(detail_html: str) -> str:
    matched = re.search(r"gaEventVideoStart\('([^']+)'", detail_html)
    if not matched:
        return ""
    payload = html.unescape(matched.group(1))
    try:
        data = json.loads(payload)
    except Exception:
        return ""
    video_url = str(data.get("video_url") or "")
    video_url = video_url.replace("\\/", "/")
    return with_https(video_url)


def extract_ajax_movie_path(detail_html: str) -> str:
    if matched := re.search(r'data-video-url="([^"]+)"', detail_html):
        return html.unescape(matched.group(1))
    if matched := re.search(r"sampleVideoRePlay\('([^']+)'\)", detail_html):
        return html.unescape(matched.group(1))
    return ""


def extract_player_url(ajax_movie_html: str) -> str:
    if matched := re.search(r'src="([^"]+)"', ajax_movie_html):
        return html.unescape(matched.group(1))
    return ""


def extract_video_url_from_player(player_html: str) -> str:
    matched = re.search(r"const\s+args\s*=\s*(\{.*?\});", player_html, flags=re.DOTALL)
    if not matched:
        return ""
    payload = matched.group(1)
    try:
        args = json.loads(payload)
    except Exception:
        return ""

    bitrates = args.get("bitrates") or []
    for item in bitrates:
        src = str(item.get("src") or "")
        if src:
            return with_https(src)

    src = str(args.get("src") or "")
    return with_https(src)


def fetch_mono_trailer(session: requests.Session, detail_url: str) -> tuple[str, str]:
    ensure_age_verified(session, detail_url)
    detail_html = fetch_html(session, detail_url)
    if AGE_PAGE_FLAG in detail_html:
        return "", "detail:age-check"

    trailer = extract_video_url_from_ga_event(detail_html)
    if trailer:
        return trailer, "detail:gaEventVideoStart"

    ajax_movie_path = extract_ajax_movie_path(detail_html)
    if not ajax_movie_path:
        return "", "detail:no-ajax-movie"

    ajax_movie_url = urljoin(detail_url, ajax_movie_path)
    ajax_movie_html = fetch_html(session, ajax_movie_url)
    player_url = with_https(urljoin(ajax_movie_url, extract_player_url(ajax_movie_html)))
    if not player_url:
        return "", "ajax-movie:no-player"

    player_html = fetch_html(session, player_url)
    trailer = extract_video_url_from_player(player_html)
    if trailer:
        return trailer, "ajax-movie:player-args"

    return "", "player:no-trailer"


def fetch_digital_trailer(session: requests.Session, detail_url: str) -> tuple[str, str]:
    ensure_age_verified(session, detail_url)
    detail_html = fetch_html(session, detail_url)
    if matched := re.search(r'"contentUrl"\s*:\s*"([^"]+)"', detail_html):
        return with_https(html.unescape(matched.group(1))), "digital:json-ld"
    return "", "digital:no-contentUrl"


def collect_detail_urls(
    session: requests.Session, search_urls: list[str], raw_number: str
) -> tuple[list[str], dict[str, str]]:
    ordered_urls: list[str] = []
    sample_map: dict[str, str] = {}
    seen: set[str] = set()

    for search_url in search_urls:
        ensure_age_verified(session, search_url)
        search_html = fetch_html(session, search_url)
        if AGE_PAGE_FLAG in search_html:
            ensure_age_verified(session, search_url)
            search_html = fetch_html(session, search_url)

        for detail_url in parse_search_detail_urls(search_html, raw_number):
            detail_key = canonicalize_detail_url(detail_url)
            if detail_key not in seen:
                seen.add(detail_key)
                ordered_urls.append(detail_url)

        for detail_url, sample_url in parse_search_sample_map(search_html).items():
            detail_key = canonicalize_detail_url(detail_url)
            sample_map[detail_key] = sample_url

    return ordered_urls, sample_map


def detect_category(detail_url: str) -> str:
    if "tv.dmm.co.jp" in detail_url:
        return "fanza_tv"
    if "tv.dmm.com" in detail_url:
        return "dmm_tv"
    if "/digital/" in detail_url or "video.dmm.co.jp" in detail_url:
        return "digital"
    if "/mono/" in detail_url:
        return "mono"
    if "/rental/" in detail_url:
        return "rental"
    if "/prime/" in detail_url:
        return "prime"
    if "/monthly/" in detail_url:
        return "monthly"
    return "other"


def run(raw_number: str) -> list[TrailerResult]:
    _, number_00, number_no_00 = normalize_number(raw_number)
    search_urls = build_search_urls(number_00, number_no_00)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
        }
    )

    detail_urls, sample_map = collect_detail_urls(session, search_urls, raw_number)
    if not detail_urls:
        return []

    mono_first = sorted(detail_urls, key=lambda each: 0 if detect_category(each) == "mono" else 1)

    results: list[TrailerResult] = []
    for detail_url in mono_first:
        detail_key = canonicalize_detail_url(detail_url)
        category = detect_category(detail_url)
        trailer_url = ""
        source = ""

        try:
            if category == "mono":
                trailer_url, source = fetch_mono_trailer(session, detail_url)
            elif category == "digital":
                trailer_url, source = fetch_digital_trailer(session, detail_url)
        except Exception as exc:
            source = f"error:{type(exc).__name__}"

        if not trailer_url and detail_key in sample_map:
            trailer_url = sample_map[detail_key]
            source = "search:sampleUrl"

        if trailer_url:
            results.append(TrailerResult(detail_url=detail_url, trailer_url=trailer_url, source=source))

    deduped_results: list[TrailerResult] = []
    seen_trailer_urls: set[str] = set()
    for item in results:
        if item.trailer_url in seen_trailer_urls:
            continue
        seen_trailer_urls.add(item.trailer_url)
        deduped_results.append(item)

    return deduped_results


def main() -> None:
    raw_number = input("请输入番号（例如 IENF-434）：").strip()
    if not raw_number:
        print("ERROR: 番号为空，已退出。")
        return

    print(f"\n开始检索：{raw_number}\n")
    results = run(raw_number)
    if not results:
        print("ERROR: 未找到可用预告片链接。")
        return

    print(f"共找到 {len(results)} 条预告片链接：\n")
    for index, item in enumerate(results, start=1):
        print(f"[{index}] 详情页: {item.detail_url}")
        print(f"    预告片: {item.trailer_url}")
        print(f"    来源: {item.source}\n")


if __name__ == "__main__":
    main()
