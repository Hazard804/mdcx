#!/usr/bin/env python3
import asyncio
import re
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, overload

import aiofiles.os
import httpx
from lxml import etree
from PIL import Image
from ping3 import ping

from ..config.manager import manager
from ..consts import GITHUB_RELEASES_API_LATEST
from ..manual import ManualConfig
from ..models.log_buffer import LogBuffer
from ..signals import signal
from ..utils import executor
from ..utils.file import check_pic_async


@overload
async def check_url(url: str, length: Literal[False] = False, real_url: bool = False) -> str | None: ...
@overload
async def check_url(url: str, length: Literal[True] = True, real_url: bool = False) -> int | None: ...
async def check_url(url: str, length: bool = False, real_url: bool = False):
    """
    检测下载链接. 失败时返回 None.

    Args:
        url (str): 要检测的 URL
        length (bool, optional): 是否返回文件大小. Defaults to False.
        real_url (bool, optional): 直接返回真实 URL 不进行后续检查. Defaults to False.
    """
    if not url:
        return

    if "http" not in url:
        signal.add_log(f"🔴 检测链接失败: 格式错误 {url}")
        return

    # 对于 AWS 图片链接，增加重试次数
    is_aws_image = "awsimgsrc.dmm.co.jp" in url
    max_retries = 3 if is_aws_image else 1

    for retry_attempt in range(max_retries):
        try:
            # 判断是否为 awsimgsrc.dmm.co.jp 图片链接
            if is_aws_image:
                # 检查参数是否已存在
                has_w = re.search(r"[?&]w=120(&|$)", url)
                has_h = re.search(r"[?&]h=90(&|$)", url)
                if not (has_w and has_h):
                    # 拼接参数
                    if "?" in url:
                        url += "&w=120&h=90"
                    else:
                        url += "?&w=120&h=90"
                # 使用 GET 请求
                response, error = await manager.computed.async_client.request("GET", url)
            else:
                # 其他情况使用 HEAD 请求
                response, error = await manager.computed.async_client.request("HEAD", url)

            # 处理请求失败的情况
            if response is None:
                if retry_attempt < max_retries - 1:
                    signal.add_log(f"🟡 检测链接失败，正在重试 ({retry_attempt + 1}/{max_retries}): {error}")
                    await asyncio.sleep(1 + retry_attempt)  # 指数退避
                    continue
                else:
                    signal.add_log(f"🔴 检测链接失败: {error}")
                    return

            # 不输出获取 dmm预览视频(trailer) 最高分辨率的测试结果到日志中
            if response.status_code == 404 and "_w.mp4" in url:
                return

            # 返回重定向的url
            true_url = str(response.url)
            if real_url:
                return true_url

            # 检查是否需要登录
            if "login" in true_url:
                signal.add_log(f"🔴 检测链接失败: 需登录 {true_url}")
                return

            # 检查是否带有图片不存在的关键词
            bad_url_keys = ["now_printing", "nowprinting", "noimage", "nopic", "media_violation"]
            for each_key in bad_url_keys:
                if each_key in true_url:
                    signal.add_log(f"🔴 检测链接失败: 图片已被网站删除 {url}")
                    return

            # 获取文件大小
            content_length = response.headers.get("Content-Length")
            if not content_length:
                # 如果没有获取到文件大小，尝试下载数据
                content, error = await manager.computed.async_client.get_content(true_url)

                if content is not None and len(content) > 0:
                    signal.add_log(f"✅ 检测链接通过: 预下载成功 {true_url}")
                    return 10240 if length else true_url
                else:
                    signal.add_log(f"🔴 检测链接失败: 未返回大小且预下载失败 {true_url}")
                    return
            # 如果返回内容的文件大小 < 8k，视为不可用
            elif int(content_length) < 8192:
                # awsimgsrc.dmm.co.jp 且 GET 请求时跳过小于8K的检查
                if "awsimgsrc.dmm.co.jp" in true_url and getattr(response.request, "method", None) == "GET":
                    signal.add_log(f"✅ 检测链接通过: awsimgsrc 小图 {true_url}")
                    return int(content_length) if length else true_url.replace("w=120&h=90", "")
                signal.add_log(f"🔴 检测链接失败: 返回大小({content_length}) < 8k {true_url}")
                return

            signal.add_log(f"✅ 检测链接通过: 返回大小({content_length}) {true_url}")
            return int(content_length) if length else true_url

        except Exception as e:
            if retry_attempt < max_retries - 1:
                signal.add_log(f"🟡 检测链接异常，正在重试 ({retry_attempt + 1}/{max_retries}): {e}")
                await asyncio.sleep(1 + retry_attempt)
                continue
            else:
                signal.add_log(f"🔴 检测链接失败: 未知异常 {e} {url}")
                return


async def get_avsox_domain() -> str:
    issue_url = "https://tellme.pw/avsox"
    response, error = await manager.computed.async_client.get_text(issue_url)
    domain = "https://avsox.click"
    if response is not None:
        res = re.findall(r'(https://[^"]+)', response)
        for s in res:
            if s and "https://avsox.com" not in s or "api.qrserver.com" not in s:
                return s
    return domain


async def get_amazon_data(req_url: str) -> tuple[bool, str]:
    """
    获取 Amazon 数据
    """
    headers = {
        "accept-encoding": "gzip, deflate, br",
        "accept-language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
        "Host": "www.amazon.co.jp",
    }
    html_info, error = await manager.computed.async_client.get_text(req_url, headers=headers, encoding="utf-8")
    if html_info is None:
        html_info, error = await manager.computed.async_client.get_text(req_url, headers=headers, encoding="utf-8")
    if html_info is None:
        session_id = ""
        ubid_acbjp = ""
        if x := re.findall(r'sessionId: "([^"]+)', html_info or ""):
            session_id = x[0]
        if x := re.findall(r"ubid-acbjp=([^ ]+)", html_info or ""):
            ubid_acbjp = x[0]
        headers_o = {
            "cookie": f"session-id={session_id}; ubid_acbjp={ubid_acbjp}",
        }
        headers.update(headers_o)
        html_info, error = await manager.computed.async_client.get_text(req_url, headers=headers, encoding="utf-8")
    if html_info is None:
        return False, error
    if "HTTP 503" in html_info:
        headers = {
            "accept-language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
            "Host": "www.amazon.co.jp",
        }
        html_info, error = await manager.computed.async_client.get_text(req_url, headers=headers, encoding="utf-8")
    if html_info is None:
        return False, error
    return True, html_info


async def get_imgsize(url) -> tuple[int, int]:
    response, _ = await manager.computed.async_client.request("GET", url, stream=True)
    if response is None or response.status_code != 200:
        return 0, 0
    file_head = BytesIO()
    chunk_size = 1024 * 10
    try:
        for chunk in response.iter_content(chunk_size):
            file_head.write(await chunk)
            try:

                def _get_size():
                    with Image.open(file_head) as img:
                        return img.size

                return await asyncio.to_thread(_get_size)
            except Exception:
                # 如果解析失败，继续下载更多数据
                continue
    except Exception:
        return 0, 0
    finally:
        response.close()

    return 0, 0


async def get_dmm_trailer(trailer_url: str) -> str:
    """
    尝试获取 dmm 最高分辨率预告片.

    Returns:
        str: 有效的最高分辨率预告片 URL.
    """
    # 如果不是 DMM 域名则直接返回
    if ".dmm.co" not in trailer_url:
        return trailer_url

    # 将相对URL转换为绝对URL
    if trailer_url.startswith("//"):
        trailer_url = "https:" + trailer_url

    # 处理临时链接格式（/pv/{temp_key}/{filename}），转换为标准格式
    # 临时链接示例: https://cc3001.dmm.co.jp/pv/{temp_key}/asfb00192_mhb_w.mp4
    # 临时链接示例: https://cc3001.dmm.co.jp/pv/{temp_key}/1start4814k.mp4
    # 临时链接示例: https://cc3001.dmm.co.jp/pv/{temp_key}/n_707agvn001_dmb_w.mp4
    # 标准格式示例: https://cc3001.dmm.co.jp/litevideo/freepv/a/asf/asfb00192/asfb00192_mhb_w.mp4
    if "/pv/" in trailer_url:
        signal.add_log("🔄 检测到临时预告片链接，开始转换...")
        filename_match = re.search(r"/pv/[^/]+/(.+?)(?:\.mp4)?$", trailer_url)
        if filename_match:
            filename_base = filename_match.group(1).replace(".mp4", "")
            # 去掉质量标记后缀
            # 1) 旧格式: _mhb_w / _hhb_w / _4k_w / _dmb_h / _sm_s 等
            # 2) 新格式: hhb / mhb / dmb / dm / sm（无 _w/_s 后缀）
            cid = re.sub(r"(_[a-z0-9]+_[a-z])?$", "", filename_base, flags=re.IGNORECASE)
            cid = re.sub(r"(hhb|mhb|dmb|dm|sm|4k)$", "", cid, flags=re.IGNORECASE)
            # 确保提取到的是有效的产品ID（包含字母和数字）
            if re.search(r"[a-z]", cid, re.IGNORECASE) and re.search(r"\d", cid):
                prefix = cid[0]
                three_char = cid[:3]
                converted_url = (
                    f"https://cc3001.dmm.co.jp/litevideo/freepv/{prefix}/{three_char}/{cid}/{filename_base}.mp4"
                )
                signal.add_log(f"📝 转换后的URL: {converted_url}")
                # 尝试验证转换后的URL，最多重试3次（仅对非404错误重试）
                for attempt in range(3):
                    try:
                        # 进行HEAD请求检测
                        response, error = await manager.computed.async_client.request("HEAD", converted_url)

                        if response is not None:
                            # 请求成功
                            if response.status_code == 404:
                                # 404错误说明转换后的URL不存在，回退到原始URL
                                signal.add_log("⚠️ 转换后的URL返回404，回退到原始链接")
                                break
                            elif 200 <= response.status_code < 300:
                                # 2xx成功，使用转换后的URL
                                signal.add_log(f"✅ 转换后的URL验证成功 (HTTP {response.status_code})")
                                trailer_url = converted_url
                                break
                            else:
                                # 其他4xx/5xx错误，继续重试
                                retry_msg = (
                                    f"🟡 转换后的URL检测失败 (HTTP {response.status_code})，"
                                    f"准备重试 ({attempt + 1}/3)..."
                                )
                                signal.add_log(retry_msg)
                                if attempt < 2:
                                    await asyncio.sleep(0.5 * (attempt + 1))
                                    continue
                                else:
                                    # 重试3次仍失败，回退到原始URL
                                    signal.add_log("⚠️ 重试3次后仍失败，回退到原始链接")
                                    break
                        else:
                            # 检查是否为 404 错误
                            if "404" in str(error):
                                # 404错误说明转换后的URL不存在，直接回退
                                signal.add_log("⚠️ 转换后的URL返回404，回退到原始链接")
                                break
                            else:
                                # 其他网络错误、超时等，重试
                                signal.add_log(f"🟡 转换后的URL网络错误: {error}，准备重试 ({attempt + 1}/3)...")
                                if attempt < 2:
                                    await asyncio.sleep(0.5 * (attempt + 1))
                                    continue
                                else:
                                    # 重试3次仍失败，回退到原始URL
                                    signal.add_log("⚠️ 重试3次后仍失败，回退到原始链接")
                                    break
                    except Exception as e:
                        # 异常处理，继续重试
                        signal.add_log(f"🟡 转换后的URL异常: {e}，准备重试 ({attempt + 1}/3)...")
                        if attempt < 2:
                            await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                        else:
                            # 重试3次仍失败，回退到原始URL
                            signal.add_log("⚠️ 重试3次后仍失败，回退到原始链接")
                            break

    """
    DMM 预览片分辨率对应关系（旧格式）:
    '_sm_w.mp4': 320*180, 3.8MB     # 最低分辨率
    '_dm_w.mp4': 560*316, 10.1MB    # 中等分辨率
    '_dmb_w.mp4': 720*404, 14.6MB   # 次高分辨率
    '_mhb_w.mp4': 720*404, 27.9MB
    '_hhb_w.mp4': 更高码率（常见约 60MB）
    '_4k_w.mp4': 最高分辨率

    旧格式其他可能的后缀: _s, _h（如 _sm_s.mp4, _dmb_h.mp4）

    DMM 预览片分辨率对应关系（新格式）:
    'sm.mp4'  < 'dm.mp4' < 'dmb.mp4' < 'mhb.mp4' < 'hhb.mp4' < '4k.mp4'
    常见示例: nima00070sm.mp4 / nima00070dm.mp4 / nima00070dmb.mp4 / nima00070mhb.mp4 / nima00070hhb.mp4 / nima000704k.mp4

    示例:
    https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00090/ssis00090_sm_w.mp4
    https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00090/ssis00090_dm_w.mp4
    https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00090/ssis00090_dmb_w.mp4
    https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00090/ssis00090_mhb_w.mp4
    https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00090/ssis00090_hhb_w.mp4
    https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00090/ssis00090_4k_w.mp4
    https://cc3001.dmm.co.jp/pv/xxxx/nima00070mhb.mp4
    https://cc3001.dmm.co.jp/pv/xxxx/nima00070hhb.mp4
    https://cc3001.dmm.co.jp/pv/xxxx/nima000704k.mp4
    """

    # 旧格式：..._sm_w.mp4 / ..._dmb_h.mp4
    if matched := re.search(r"(.+)_([a-z0-9]+)_([a-z])\.mp4$", trailer_url, flags=re.IGNORECASE):
        base_url, quality_level, suffix_char = matched.groups()
        quality_level = quality_level.lower()
        suffix_char = suffix_char.lower()
        quality_levels = ("sm", "dm", "dmb", "mhb", "hhb", "4k")

        if quality_level in quality_levels:
            current_index = quality_levels.index(quality_level)
            suffix_candidates = (suffix_char,) + tuple(s for s in ("w", "s", "h") if s != suffix_char)
            for i in range(len(quality_levels) - 1, current_index, -1):
                higher_quality = quality_levels[i]
                for test_suffix_char in suffix_candidates:
                    test_url = base_url + f"_{higher_quality}_{test_suffix_char}.mp4"
                    if await check_url(test_url):
                        signal.add_log(
                            f"🎬 DMM trailer 升级(旧格式): {quality_level}_{suffix_char} -> "
                            f"{higher_quality}_{test_suffix_char}"
                        )
                        signal.add_log(f"🎬 DMM trailer URL: {trailer_url} -> {test_url}")
                        return test_url
            signal.add_log(f"🎬 DMM trailer 保持原质量(旧格式): {quality_level}_{suffix_char} {trailer_url}")
        return trailer_url

    # 新格式：...nima00070mhb.mp4 / ...nima00070hhb.mp4（无 _w/_s 后缀）
    if matched := re.search(r"(.+?)(sm|dm|dmb|mhb|hhb|4k)\.mp4$", trailer_url, flags=re.IGNORECASE):
        base_url, quality_level = matched.groups()
        quality_level = quality_level.lower()
        quality_levels = ("sm", "dm", "dmb", "mhb", "hhb", "4k")

        if quality_level in quality_levels:
            current_index = quality_levels.index(quality_level)
            for i in range(len(quality_levels) - 1, current_index, -1):
                higher_quality = quality_levels[i]
                test_url = base_url + f"{higher_quality}.mp4"
                if await check_url(test_url):
                    signal.add_log(f"🎬 DMM trailer 升级(新格式): {quality_level} -> {higher_quality}")
                    signal.add_log(f"🎬 DMM trailer URL: {trailer_url} -> {test_url}")
                    return test_url
            signal.add_log(f"🎬 DMM trailer 保持原质量(新格式): {quality_level} {trailer_url}")

    return trailer_url


def _ping_host_thread(host_address: str, result_list: list[int | None], i: int) -> None:
    response = ping(host_address, timeout=1)
    result_list[i] = int(response * 1000) if response else 0


# todo 可以移除 ping, 仅靠 http request 检测网络连通性
def ping_host(host_address: str) -> str:
    count = manager.config.retry
    result_list: list[int | None] = [None] * count
    thread_list: list[threading.Thread] = [None] * count  # type: ignore
    for i in range(count):
        thread_list[i] = threading.Thread(target=_ping_host_thread, args=(host_address, result_list, i))
        thread_list[i].start()
    for i in range(count):
        thread_list[i].join()
    new_list = [each for each in result_list if each]
    return (
        f"  ⏱ Ping {int(sum(new_list) / len(new_list))} ms ({len(new_list)}/{count})"
        if new_list
        else f"  🔴 Ping - ms (0/{count})"
    )


def check_version() -> int | None:
    if manager.config.update_check:
        url = GITHUB_RELEASES_API_LATEST
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "mdcx-update-check",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        timeout = max(float(manager.config.timeout), 5.0)
        configured_proxy = manager.config.proxy.strip() if manager.config.use_proxy and manager.config.proxy else ""
        request_proxies = [configured_proxy] if configured_proxy else []
        request_proxies.append("")

        last_error = ""
        for proxy in dict.fromkeys(request_proxies):
            try:
                client_kwargs: dict[str, Any] = {"timeout": timeout, "follow_redirects": True}
                if proxy:
                    client_kwargs["proxy"] = proxy
                with httpx.Client(**client_kwargs) as client:
                    response = client.get(url, headers=headers)
            except Exception as e:
                last_error = str(e)
                continue

            if response.status_code != 200:
                if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
                    reset_raw = response.headers.get("x-ratelimit-reset", "")
                    if reset_raw.isdigit():
                        reset_at = time.strftime("%H:%M:%S", time.localtime(int(reset_raw)))
                        last_error = f"GitHub API 限流（403，剩余 0，预计重置 {reset_at}）"
                    else:
                        last_error = "GitHub API 限流（403，剩余 0）"
                else:
                    last_error = f"HTTP {response.status_code}"
                continue

            try:
                latest_version = int(str(response.json()["tag_name"]).strip())
                return latest_version
            except Exception:
                signal.add_log(f"❌ 获取最新版本失败！{response.text}")
                return None

        if last_error:
            signal.add_log(f"❌ 获取最新版本失败！{last_error}")
    return None


def check_theporndb_api_token() -> str:
    tips = "✅ 连接正常! "
    api_token = manager.config.theporndb_api_token
    url = "https://api.theporndb.net/scenes/hash/8679fcbdd29fa735"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if not api_token:
        tips = "❌ 未填写 API Token，影响欧美刮削！可在「设置」-「网络」添加！"
    else:
        response, err = executor.run(manager.computed.async_client.request("GET", url, headers=headers))
        if response is None:
            tips = f"❌ ThePornDB 连接失败: {err}"
            signal.show_log_text(tips)
            return tips
        if response.status_code == 401 and "Unauthenticated" in str(response.text):
            tips = "❌ API Token 错误！影响欧美刮削！请到「设置」-「网络」中修改。"
        elif response.status_code == 200:
            tips = "✅ 连接正常！" if response.json().get("data") else "❌ 返回数据异常！"
        else:
            tips = f"❌ 连接失败！请检查网络或代理设置！ {response.status_code} {response.text}"
    signal.show_log_text(tips.replace("❌", " ❌ ThePornDB").replace("✅", " ✅ ThePornDB"))
    return tips


async def _get_pic_by_google(pic_url):
    google_keyused = manager.computed.google_keyused
    google_keyword = manager.computed.google_keyword
    req_url = f"https://www.google.com/searchbyimage?sbisrc=2&image_url={pic_url}"
    # req_url = f'https://lens.google.com/uploadbyurl?url={pic_url}&hl=zh-CN&re=df&ep=gisbubu'
    response, error = await manager.computed.async_client.get_text(req_url)
    big_pic = True
    if response is None:
        return "", (0, 0), False
    url_list = re.findall(r'a href="([^"]+isz:l[^"]+)">', response)
    url_list_middle = re.findall(r'a href="([^"]+isz:m[^"]+)">', response)
    if not url_list and url_list_middle:
        url_list = url_list_middle
        big_pic = False
    if url_list:
        req_url = "https://www.google.com" + url_list[0].replace("amp;", "")
        response, error = await manager.computed.async_client.get_text(req_url)
    if response is None:
        return "", (0, 0), False
    url_list = re.findall(r'\["(http[^"]+)",(\d{3,4}),(\d{3,4})\],[^[]', response)
    # 优先下载放前面
    new_url_list = []
    for each_url in url_list.copy():
        if int(each_url[2]) < 800:
            url_list.remove(each_url)

    for each_key in google_keyused:
        for each_url in url_list.copy():
            if each_key in each_url[0]:
                new_url_list.append(each_url)
                url_list.remove(each_url)
    # 只下载关时，追加剩余地址
    if "goo_only" not in [item.value for item in manager.config.download_hd_pics]:
        new_url_list += url_list
    # 解析地址
    for each in new_url_list:
        temp_url = each[0]
        for temp_keyword in google_keyword:
            if temp_keyword in temp_url:
                break
        else:
            h = int(each[1])
            w = int(each[2])
            if w > h and w / h < 1.4:  # thumb 被拉高时跳过
                continue

            p_url = temp_url.encode("utf-8").decode("unicode_escape")  # url中的Unicode字符转义，不转义，url请求会失败
            if "m.media-amazon.com" in p_url:
                p_url = re.sub(r"\._[_]?AC_[^\.]+\.", ".", p_url)
                pic_size = await get_imgsize(p_url)
                if pic_size[0]:
                    return p_url, pic_size, big_pic
            else:
                url = await check_url(p_url)
                if url:
                    pic_size = (w, h)
                    return url, pic_size, big_pic
    return "", (0, 0), False


async def get_big_pic_by_google(pic_url, poster=False) -> tuple[str, tuple[int, int]]:
    url, pic_size, big_pic = await _get_pic_by_google(pic_url)
    if not poster:
        if big_pic or (
            pic_size and int(pic_size[0]) > 800 and int(pic_size[1]) > 539
        ):  # cover 有大图时或者图片高度 > 800 时使用该图片
            return url, pic_size
        return "", (0, 0)
    if url and int(pic_size[1]) < 1000:  # poster，图片高度小于 1500，重新搜索一次
        url, pic_size, big_pic = await _get_pic_by_google(url)
    if pic_size and (
        big_pic or "blogger.googleusercontent.com" in url or int(pic_size[1]) > 560
    ):  # poster，大图或高度 > 560 时，使用该图片
        return url, pic_size
    else:
        return "", (0, 0)


async def get_actorname(number: str) -> tuple[bool, str]:
    # 获取真实演员名字
    url = f"https://av-wiki.net/?s={number}"
    res, error = await manager.computed.async_client.get_text(url)
    if res is None:
        return False, f"Error: {error}"
    html_detail = etree.fromstring(res, etree.HTMLParser(encoding="utf-8"))
    actor_box = html_detail.xpath('//ul[@class="post-meta clearfix"]')
    for each in actor_box:
        actor_name = each.xpath('li[@class="actress-name"]/a/text()')
        actor_number = each.xpath('li[@class="actress-name"]/following-sibling::li[last()]/text()')
        if actor_number and (
            actor_number[0].upper().endswith(number.upper()) or number.upper().endswith(actor_number[0].upper())
        ):
            return True, ",".join(actor_name)
    return False, "No Result!"


async def get_yesjav_title(movie_number: str) -> str:
    yesjav_url = f"http://www.yesjav101.com/search.asp?q={movie_number}&"
    movie_title = ""
    response, error = await manager.computed.async_client.get_text(yesjav_url)
    if response is not None:
        parser = etree.HTMLParser(encoding="utf-8")
        html = etree.HTML(response, parser)
        movie_title = html.xpath(
            '//dl[@id="zi"]/p/font/a/b[contains(text(), $number)]/../../a[contains(text(), "中文字幕")]/text()',
            number=movie_number,
        )
        if movie_title:
            movie_title = movie_title[0]
            for each in ManualConfig.CHAR_LIST:
                movie_title = movie_title.replace(each, "")
            movie_title = movie_title.strip()
    return movie_title


async def download_file_with_filepath(url: str, file_path: Path, folder_new_path: Path) -> bool:
    if not url:
        return False

    if not await aiofiles.os.path.exists(folder_new_path):
        await aiofiles.os.makedirs(folder_new_path)
    try:
        if await manager.computed.async_client.download(url, file_path):
            return True
    except Exception:
        pass
    LogBuffer.log().write(f"\n 🥺 Download failed! {url}")
    return False


async def download_extrafanart_task(task: tuple[str, Path, Path, str]) -> bool:
    extrafanart_url, extrafanart_file_path, extrafanart_folder_path, extrafanart_name = task
    if await download_file_with_filepath(extrafanart_url, extrafanart_file_path, extrafanart_folder_path):
        if await check_pic_async(extrafanart_file_path):
            return True
    else:
        LogBuffer.log().write(f"\n 💡 {extrafanart_name} download failed! ( {extrafanart_url} )")
    return False
