import asyncio
import json
import os
import re
import time
import traceback
from pathlib import Path
from typing import Literal, cast
from urllib.parse import quote, urlencode

import aiofiles
import aiofiles.os
from parsel import Selector

from ..base.web import download_file_with_filepath
from ..config.enums import EmbyAction
from ..config.manager import manager
from ..config.resources import resources
from ..image import cut_pic, fix_pic_async
from ..signals import signal
from ..utils import get_used_time

JELLYFIN_PERSON_FIELDS = ("Overview", "ProviderIds", "ProductionLocations", "Taglines", "Genres", "Tags")


def _is_jellyfin_server() -> bool:
    return manager.config.server_type == "jellyfin"


def _build_jellyfin_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
    request_headers = dict(headers or {})
    request_headers["Authorization"] = f'MediaBrowser Token="{manager.config.api_key}"'
    return request_headers


def _append_query(url: str, params: dict[str, str | None]) -> str:
    query = urlencode({key: value for key, value in params.items() if value not in ("", None)})
    return f"{url}?{query}" if query else url


async def _get_actor_detail(actor: dict) -> tuple[dict | None, str]:
    # Jellyfin 的 /Persons 列表已可返回补全信息所需字段，避免逐个演员再请求一次详情接口。
    if _is_jellyfin_server() and any(field in actor for field in JELLYFIN_PERSON_FIELDS):
        return actor, ""

    _, actor_person, _, _, _, _ = _generate_server_url(actor)
    headers = _build_jellyfin_headers() if _is_jellyfin_server() else None
    return await manager.computed.async_client.get_json(actor_person, headers=headers, use_proxy=False)


async def update_emby_actor_photo() -> None:
    signal.change_buttons_status.emit()
    server_type = manager.config.server_type
    if "emby" == server_type:
        signal.show_log_text("👩🏻 开始补全 Emby 演员头像...")
    else:
        signal.show_log_text("👩🏻 开始补全 Jellyfin 演员头像...")
    actor_list = await _get_emby_actor_list()
    gfriends_actor_data = await _get_gfriends_actor_data()
    if gfriends_actor_data:
        await _update_emby_actor_photo_execute(actor_list, gfriends_actor_data)
    signal.reset_buttons_status.emit()


async def _get_emby_actor_list() -> list[dict]:
    base_url = str(manager.config.emby_url).rstrip("/")
    headers = None
    # 获取 emby 的演员列表
    if "emby" == manager.config.server_type:
        server_name = "Emby"
        url = base_url + "/emby/Persons?api_key=" + manager.config.api_key
        # http://192.168.5.191:8096/emby/Persons?api_key=ee9a2f2419704257b1dd60b975f2d64e
        # http://192.168.5.191:8096/emby/Persons/梦乃爱华?api_key=ee9a2f2419704257b1dd60b975f2d64e
        if manager.config.user_id:
            url += f"&userid={manager.config.user_id}"
    else:
        server_name = "Jellyfin"
        headers = _build_jellyfin_headers()
        url = _append_query(
            base_url + "/Persons",
            {
                "personTypes": "Actor",
                "fields": ",".join(JELLYFIN_PERSON_FIELDS),
                "enableImages": "true",
                "userId": manager.config.user_id,
            },
        )

    signal.show_log_text(f"⏳ 连接 {server_name} 服务器...")

    if not manager.config.api_key:
        signal.show_log_text(f"🔴 {server_name} API 密钥未填写！")
        signal.show_log_text("================================================================================")
        return []

    response, error = await manager.computed.async_client.get_json(url, headers=headers, use_proxy=False)
    if response is None:
        signal.show_log_text(f"🔴 {server_name} 连接失败！请检查 {server_name} 地址 和 API 密钥是否正确填写！ {error}")
        return []

    actor_list = response.get("Items", [])
    signal.show_log_text(f"✅ {server_name} 连接成功！共有 {len(actor_list)} 个演员！")
    if not actor_list:
        signal.show_log_text("================================================================================")
    return actor_list


async def _upload_actor_photo(url: str, pic_path: Path) -> tuple[bool, str]:
    try:
        async with aiofiles.open(pic_path, "rb") as f:
            content = await f.read()
        header = {"Content-Type": "image/jpeg" if pic_path.suffix in (".jpg", ".jpeg") else "image/png"}
        if _is_jellyfin_server():
            header = _build_jellyfin_headers(header)
        r, err = await manager.computed.async_client.post_content(
            url=url, data=content, headers=header, use_proxy=False
        )
        return r is not None, err
    except Exception as e:
        signal.show_log_text(traceback.format_exc())
        return False, f"上传头像失败: {url} {pic_path} {str(e)}"


def _generate_server_url(actor_js: dict) -> tuple[str, str, str, str, str, str]:
    server_type = manager.config.server_type
    emby_url = str(manager.config.emby_url).rstrip("/")
    api_key = manager.config.api_key
    actor_name = quote(actor_js["Name"], safe="")
    actor_id = actor_js["Id"]
    server_id = actor_js.get("ServerId", "")

    if "emby" == server_type:
        actor_homepage = f"{emby_url}/web/index.html#!/item?id={actor_id}&serverId={server_id}"
        actor_person = f"{emby_url}/emby/Persons/{actor_name}?api_key={api_key}"
        pic_url = f"{emby_url}/emby/Items/{actor_id}/Images/Primary?api_key={api_key}"
        backdrop_url = f"{emby_url}/emby/Items/{actor_id}/Images/Backdrop?api_key={api_key}"
        backdrop_url_0 = f"{emby_url}/emby/Items/{actor_id}/Images/Backdrop/0?api_key={api_key}"
        update_url = f"{emby_url}/emby/Items/{actor_id}?api_key={api_key}"
    else:
        actor_homepage = f"{emby_url}/web/index.html#!/details?id={actor_id}&serverId={server_id}"
        actor_person = _append_query(f"{emby_url}/Persons/{actor_name}", {"userId": manager.config.user_id})
        pic_url = f"{emby_url}/Items/{actor_id}/Images/Primary"
        backdrop_url = f"{emby_url}/Items/{actor_id}/Images/Backdrop"
        backdrop_url_0 = f"{emby_url}/Items/{actor_id}/Images/Backdrop/0"
        update_url = f"{emby_url}/Items/{actor_id}"
    return actor_homepage, actor_person, pic_url, backdrop_url, backdrop_url_0, update_url


async def _get_gfriends_actor_data() -> dict[str, str] | Literal[False] | None:
    emby_on = manager.config.emby_on
    gfriends_github = manager.config.gfriends_github
    raw_url = f"{gfriends_github}".replace("github.com/", "raw.githubusercontent.com/").replace("://www.", "://")
    # 'https://raw.githubusercontent.com/gfriends/gfriends'

    if EmbyAction.ACTOR_PHOTO_NET in emby_on:
        update_data = False
        signal.show_log_text("⏳ 连接 Gfriends 网络头像库...")
        net_url = f"{gfriends_github}/commits/master/Filetree.json"
        response, error = await manager.computed.async_client.get_text(net_url)
        if response is None:
            signal.show_log_text("🔴 Gfriends 查询最新数据更新时间失败！")
            net_float = 0
            update_data = True
        else:
            try:
                date_time = re.findall(r'committedDate":"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', response)
                lastest_time = time.strptime(date_time[0], "%Y-%m-%dT%H:%M:%S")
                net_float = time.mktime(lastest_time) - time.timezone
                net_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(net_float))
            except Exception:
                signal.show_log_text("🔴 Gfriends 历史页面解析失败！请向开发者报告! ")
                return False
            signal.show_log_text(f"✅ Gfriends 连接成功！最新数据更新时间: {net_time}")

        # 更新：本地无文件时；更新时间过期；本地文件读取失败时，重新更新
        gfriends_json_path = resources.u("gfriends.json")
        if (
            not await aiofiles.os.path.exists(gfriends_json_path)
            or await aiofiles.os.path.getmtime(gfriends_json_path) < 1657285200
        ):
            update_data = True
        else:
            try:
                async with aiofiles.open(gfriends_json_path, encoding="utf-8") as f:
                    content = await f.read()
                    gfriends_actor_data = json.loads(content)
            except Exception:
                signal.show_log_text("🔴 本地缓存数据读取失败！需重新缓存！")
                update_data = True
            else:
                local_float = await aiofiles.os.path.getmtime(gfriends_json_path)
                local_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(local_float))
                if not net_float or net_float > local_float:
                    signal.show_log_text(f"🍉 本地缓存数据需要更新！本地数据更新时间: {local_time}")
                    update_data = True
                else:
                    signal.show_log_text(f"✅ 本地缓存数据无需更新！本地数据更新时间: {local_time}")
                    return gfriends_actor_data

        # 更新数据
        if update_data:
            signal.show_log_text("⏳ 开始缓存 Gfriends 最新数据表...")
            filetree_url = f"{raw_url}/master/Filetree.json"
            response, error = await manager.computed.async_client.get_content(filetree_url)
            if response is None:
                signal.show_log_text("🔴 Gfriends 数据表获取失败！补全已停止！")
                return False
            async with aiofiles.open(gfriends_json_path, "wb") as f:
                await f.write(response)
            signal.show_log_text("✅ Gfriends 数据表已缓存！")
            try:
                async with aiofiles.open(gfriends_json_path, encoding="utf-8") as f:
                    content = await f.read()
                    gfriends_actor_data = json.loads(content)
            except Exception:
                signal.show_log_text("🔴 本地缓存数据读取失败！补全已停止！")
                return False
            else:
                content = gfriends_actor_data.get("Content")
                new_gfriends_actor_data = {}
                content_list = list(content.keys())
                content_list.sort()
                for each_key in content_list:
                    for key, value in content.get(each_key).items():
                        if key not in new_gfriends_actor_data:
                            # https://raw.githubusercontent.com/gfriends/gfriends/master/Content/z-Derekhsu/%E5%A4%A2%E4%B9%83%E3%81%82%E3%81%84%E3%81%8B.jpg
                            actor_url = f"{raw_url}/master/Content/{each_key}/{value}"
                            new_gfriends_actor_data[key] = actor_url
                async with aiofiles.open(gfriends_json_path, "w", encoding="utf-8") as f:
                    json_content = json.dumps(
                        new_gfriends_actor_data,
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=4,
                        separators=(",", ": "),
                    )
                    await f.write(json_content)
                return new_gfriends_actor_data
    else:
        return await asyncio.to_thread(_get_local_actor_photo)


async def _get_graphis_pic(actor_name: str) -> tuple[Path | None, Path | None, str]:
    emby_on = manager.config.emby_on

    # 生成图片路径和请求地址
    actor_folder = resources.u("actor/graphis")
    pic_old = actor_folder / f"{actor_name}-org-old.jpg"
    fix_old = actor_folder / f"{actor_name}-fix-old.jpg"
    big_old = actor_folder / f"{actor_name}-big-old.jpg"
    pic_new = actor_folder / f"{actor_name}-org-new.jpg"
    fix_new = actor_folder / f"{actor_name}-fix-new.jpg"
    big_new = actor_folder / f"{actor_name}-big-new.jpg"
    if EmbyAction.GRAPHIS_NEW in emby_on:
        pic_path = pic_new
        backdrop_path = big_new
        if EmbyAction.GRAPHIS_BACKDROP not in emby_on:
            backdrop_path = fix_new
        url = f"https://graphis.ne.jp/monthly/?K={actor_name}"
    else:
        pic_path = pic_old
        backdrop_path = big_old
        if EmbyAction.GRAPHIS_BACKDROP not in emby_on:
            backdrop_path = fix_old
        url = f"https://graphis.ne.jp/monthly/?S=1&K={actor_name}"  # https://graphis.ne.jp/monthly/?S=1&K=夢乃あいか

    # 查看本地有没有缓存
    logs = ""
    has_pic = False
    has_backdrop = False
    if await aiofiles.os.path.isfile(pic_path):
        has_pic = True
    if await aiofiles.os.path.isfile(backdrop_path):
        has_backdrop = True
    if EmbyAction.GRAPHIS_FACE not in emby_on:
        pic_path = None
        if has_backdrop:
            logs += "✅ graphis.ne.jp 本地背景！ "
            return None, backdrop_path, logs
    elif EmbyAction.GRAPHIS_BACKDROP not in emby_on:
        if has_pic:
            logs += "✅ graphis.ne.jp 本地头像！ "
            return pic_path, None, logs
    elif has_pic and has_backdrop:
        return pic_path, backdrop_path, ""

    # 请求图片
    res, error = await manager.computed.async_client.get_text(url)
    if res is None:
        logs += f"🔴 graphis.ne.jp 请求失败！\n{error}"
        return None, None, logs
    html = Selector(res)
    src = html.xpath("//div[@class='gp-model-box']/ul/li/a/img/@src").getall()
    jp_name = html.xpath("//li[@class='name-jp']/span/text()").getall()
    if actor_name not in jp_name:
        # logs += '🍊 graphis.ne.jp 无结果！'
        return None, None, logs
    small_pic = src[jp_name.index(actor_name)]
    big_pic = small_pic.replace("/prof.jpg", "/model.jpg")

    # 保存图片
    if not has_pic and pic_path:
        if await download_file_with_filepath(small_pic, pic_path, actor_folder):
            logs += "🍊 使用 graphis.ne.jp 头像！ "
            if EmbyAction.GRAPHIS_BACKDROP not in emby_on:
                if not has_backdrop:
                    await fix_pic_async(pic_path, backdrop_path)
                return pic_path, backdrop_path, logs
        else:
            logs += "🔴 graphis.ne.jp 头像获取失败！ "
    if not has_backdrop and EmbyAction.GRAPHIS_BACKDROP in emby_on:
        if await download_file_with_filepath(big_pic, backdrop_path, actor_folder):
            logs += "🍊 使用 graphis.ne.jp 背景！ "
            await fix_pic_async(backdrop_path, backdrop_path)
        else:
            logs += "🔴 graphis.ne.jp 背景获取失败！ "
    return pic_path, backdrop_path, logs


async def _update_emby_actor_photo_execute(actor_list: list[dict], gfriends_actor_data: dict[str, str]) -> None:
    start_time = time.time()
    emby_on = manager.config.emby_on
    actor_folder = resources.u("actor")

    i = 0
    succ = 0
    fail = 0
    skip = 0
    count_all = len(actor_list)
    for actor_js in actor_list:
        i += 1
        deal_percent = f"{i / count_all:.2%}"
        # Emby 有头像时处理
        actor_name = actor_js["Name"]
        actor_imagetages = actor_js.get("ImageTags")
        actor_backdrop_imagetages = actor_js.get("BackdropImageTags") or []
        if " " in actor_name:
            skip += 1
            continue
        actor_homepage, actor_person, pic_url, backdrop_url, backdrop_url_0, update_url = _generate_server_url(actor_js)
        if actor_imagetages and EmbyAction.ACTOR_PHOTO_MISS in emby_on:
            # self.show_log_text(f'\n{deal_percent} ✅ {i}/{count_all} 已有头像！跳过！ 👩🏻 {actor_name} \n{actor_homepage}')
            skip += 1
            continue

        # 获取演员日文名字
        actor_name_data = resources.get_actor_data(actor_name)
        has_name = actor_name_data["has_name"]
        jp_name = actor_name
        if has_name:
            jp_name = actor_name_data["jp"]

        # graphis 判断
        pic_path, backdrop_path, logs = None, None, ""
        if (
            EmbyAction.ACTOR_PHOTO_NET in emby_on
            and has_name
            and (EmbyAction.GRAPHIS_BACKDROP in emby_on or EmbyAction.GRAPHIS_FACE in emby_on)
        ):
            pic_path, backdrop_path, logs = await _get_graphis_pic(jp_name)

        # 要上传的头像图片未找到时
        if not pic_path:
            pic_path = gfriends_actor_data.get(f"{jp_name}.jpg")
            if not pic_path:
                pic_path = gfriends_actor_data.get(f"{jp_name}.png")
            if not pic_path:
                if actor_imagetages:
                    signal.show_log_text(
                        f"\n{deal_percent} ✅ {i}/{count_all} 没有找到头像！继续使用原有头像！ 👩🏻 {actor_name} {logs}\n{actor_homepage}"
                    )
                    succ += 1
                    continue
                signal.show_log_text(
                    f"\n{deal_percent} 🔴 {i}/{count_all} 没有找到头像！ 👩🏻 {actor_name}  {logs}\n{actor_homepage}"
                )
                fail += 1
                continue
        else:
            pass

        # 头像需要下载时
        if isinstance(pic_path, str) and "https://" in pic_path:
            file_name = pic_path.split("/")[-1]
            file_name = re.search(r"^[^?]+", file_name)
            file_name = file_name.group(0) if file_name else f"{actor_name}.jpg"
            file_path = actor_folder / file_name
            if not await aiofiles.os.path.isfile(file_path):
                if not await download_file_with_filepath(pic_path, file_path, actor_folder):
                    signal.show_log_text(
                        f"\n{deal_percent} 🔴 {i}/{count_all} 头像下载失败！ 👩🏻 {actor_name}  {logs}\n{actor_homepage}"
                    )
                    fail += 1
                    continue
            pic_path = file_path
        pic_path = cast(Path, pic_path)

        # 检查背景是否存在
        if not backdrop_path:
            backdrop_path = pic_path.with_name(pic_path.stem + "-big.jpg")
            if not await aiofiles.os.path.isfile(backdrop_path):
                await fix_pic_async(pic_path, backdrop_path)

        # 检查图片尺寸并裁剪为2:3
        await asyncio.to_thread(cut_pic, pic_path)

        # 清理旧图片（backdrop可以多张，不清理会一直累积）
        if actor_backdrop_imagetages:
            for _ in range(len(actor_backdrop_imagetages)):
                headers = _build_jellyfin_headers() if _is_jellyfin_server() else None
                await manager.computed.async_client.request("DELETE", backdrop_url_0, headers=headers, use_proxy=False)

        # 上传头像到 emby
        r, err = await _upload_actor_photo(pic_url, pic_path)
        if not r:
            r, err = await _upload_actor_photo(backdrop_url, backdrop_path)
        if r:
            if not logs or logs == "🍊 graphis.ne.jp 无结果！":
                if EmbyAction.ACTOR_PHOTO_NET in manager.config.emby_on:
                    logs += " ✅ 使用 Gfriends 头像和背景！"
                else:
                    logs += " ✅ 使用本地头像库头像和背景！"
            signal.show_log_text(
                f"\n{deal_percent} ✅ {i}/{count_all} 头像更新成功！ 👩🏻 {actor_name}  {logs}\n{actor_homepage}"
            )
            succ += 1
        else:
            signal.show_log_text(
                f"\n{deal_percent} 🔴 {i}/{count_all} 头像上传失败！ 👩🏻 {actor_name}  {logs}\n{actor_homepage} {err}"
            )
            fail += 1
    signal.show_log_text(
        f"\n\n 🎉🎉🎉 演员头像补全完成！用时: {get_used_time(start_time)}秒 成功: {succ} 失败: {fail} 跳过: {skip}\n"
    )


def _get_local_actor_photo() -> dict[str, str] | Literal[False]:
    """This function is intended to be sync."""
    actor_photo_folder = manager.config.actor_photo_folder
    if actor_photo_folder == "" or not os.path.isdir(actor_photo_folder):
        signal.show_log_text("🔴 本地头像库文件夹不存在！补全已停止！")
        signal.show_log_text("================================================================================")
        return False
    else:
        local_actor_photo_dic = {}
        all_files = os.walk(actor_photo_folder)
        for root, dirs, files in all_files:
            for file in files:
                if (file.endswith("jpg") or file.endswith("png")) and file not in local_actor_photo_dic:
                    pic_path = os.path.join(root, file)
                    local_actor_photo_dic[file] = pic_path

        if not local_actor_photo_dic:
            signal.show_log_text("🔴 本地头像库文件夹未发现头像图片！请把图片放到文件夹中！")
            signal.show_log_text("================================================================================")
            return False
        return local_actor_photo_dic


if __name__ == "__main__":
    asyncio.run(_get_gfriends_actor_data())
