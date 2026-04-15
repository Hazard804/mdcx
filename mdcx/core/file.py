import os
import re
import shutil
import traceback
from pathlib import Path

import aiofiles
import aiofiles.os

from ..base.number import remove_escape_string
from ..config.enums import CDChar, Switch
from ..config.manager import manager
from ..consts import IS_MAC, IS_WINDOWS
from ..models.enums import FileMode
from ..models.flags import Flags
from ..models.log_buffer import LogBuffer
from ..models.types import BaseCrawlerResult, CrawlersResult, FileInfo, OtherInfo
from ..number import get_file_number, get_number_letters, is_uncensored
from ..signals import signal
from ..utils import nfd2c, split_path
from ..utils.file import copy_file_async, delete_file_async, move_file_async
from ..utils.path import showFilePath
from .utils import render_name_template


async def creat_folder(
    other: OtherInfo,
    json_data: BaseCrawlerResult,
    folder_new_path: Path,
    file_path: Path,
    file_new_path: Path,
    thumb_new_path_with_filename: Path,
    poster_new_path_with_filename: Path,
) -> bool:
    """判断是否创建文件夹，目标文件是否有重复文件。file_new_path是最终路径"""

    other.dont_move_movie = False  # 不需要移动和重命名视频
    other.del_file_path = False  # 在 move movie 时需要删除自己，自己是软链接，目标是原始文件
    dont_creat_folder = False  # 不需要创建文件夹

    # 正常模式、视频模式时，软链接关，成功后不移动文件开时，这时不创建文件夹
    if manager.config.main_mode < 3 and manager.config.soft_link == 0 and not manager.config.success_file_move:
        dont_creat_folder = True

    # 更新模式、读取模式，选择更新c文件时，不创建文件夹
    if manager.config.main_mode > 2 and manager.config.update_mode == "c":
        dont_creat_folder = True

    # 如果不需要创建文件夹，当不重命名时，直接返回
    if dont_creat_folder:
        if not manager.config.success_file_rename:
            other.dont_move_movie = True
            return True

    # 如果不存在目标文件夹，则创建文件夹
    elif not await aiofiles.os.path.isdir(folder_new_path):
        try:
            await aiofiles.os.makedirs(folder_new_path)
            LogBuffer.log().write("\n 🍀 Folder done! (new)")
            return True
        except Exception as e:
            if not await aiofiles.os.path.exists(folder_new_path):
                LogBuffer.log().write(f"\n 🔴 创建目录失败! \n    {str(e)}")
                if len(str(folder_new_path)) > 250:
                    LogBuffer.log().write("可能是目录名过长！")
                    LogBuffer.error().write("创建文件夹失败！可能是目录名过长！")
                else:
                    LogBuffer.log().write("请检查是否有写入权限！")
                    LogBuffer.error().write("创建文件夹失败！请检查是否有写入权限！")
                return False

    try:
        fn_stat = await aiofiles.os.stat(file_new_path)
    except (OSError, ValueError):
        # 目标文件不存在
        return True

    f_stat = await aiofiles.os.stat(file_path)
    # 二者指向同一个文件
    if os.path.samestat(fn_stat, f_stat):
        other.dont_move_movie = True
        if await aiofiles.os.path.exists(thumb_new_path_with_filename):
            other.thumb_path = thumb_new_path_with_filename
        if await aiofiles.os.path.exists(poster_new_path_with_filename):
            other.poster_path = poster_new_path_with_filename
        return True
    else:
        json_data.title = "成功文件夹已存在同名文件!"
        LogBuffer.error().write(f"成功文件夹已存在同名文件! \n ❗️ 当前文件: {file_path} \n ❗️ 已存在: {file_new_path} ")
        return False


async def move_movie(other: OtherInfo, file_info: FileInfo, file_path: Path, file_new_path: Path) -> bool:
    # 明确不需要移动的，直接返回
    if other.dont_move_movie:
        LogBuffer.log().write(f"\n 🍀 Movie done! \n 🙉 [Movie] {file_path}")
        return True

    # 明确要删除自己的，删除后返回
    if other.del_file_path:
        await delete_file_async(file_path)
        LogBuffer.log().write(f"\n 🍀 Movie done! \n 🙉 [Movie] {file_new_path}")
        file_info.file_path = file_new_path
        return True

    # 软链接模式开时，先删除目标文件，再创建软链接(需考虑自身是软链接的情况)
    if manager.config.soft_link == 1:
        raw = file_path
        # 自身是软链接时，获取真实路径
        file_path = file_path.resolve()
        # 删除目标路径存在的文件，否则会创建失败，
        await delete_file_async(file_new_path)
        try:
            await aiofiles.os.symlink(file_path, file_new_path)
            file_info.file_path = file_new_path
            LogBuffer.log().write(f"\n 🍀 创建软链接完成 \n    软链接文件: {file_new_path} \n    源文件: {file_path}")
            return True
        except Exception as e:
            if IS_WINDOWS:
                LogBuffer.log().write(
                    f"\n 🔴 创建软链接失败. 注意：Windows 平台输出目录必须是本地磁盘, 不支持挂载的 NAS 盘或网盘. 如果是本地磁盘, 请尝试以管理员身份运行！\n{str(e)}\n 🙉 [Movie] {raw}"
                )
            else:
                LogBuffer.log().write(f"\n 🔴 创建软链接失败\n{str(e)}\n 🙉 [Movie] {raw}")
            signal.show_traceback_log(traceback.format_exc())
            signal.show_log_text(traceback.format_exc())
            return False

    # 硬链接模式开时，创建硬链接
    elif manager.config.soft_link == 2:
        try:
            await delete_file_async(file_new_path)
            await aiofiles.os.link(file_path, file_new_path)
            file_info.file_path = file_new_path
            LogBuffer.log().write(f"\n 🍀 硬链接! \n    HadrLink file: {file_new_path} \n    Source file: {file_path}")
            return True
        except Exception as e:
            if IS_MAC:
                LogBuffer.log().write(
                    "\n 🔴 创建硬链接失败. "
                    "注意：硬链接要求待刮削文件和输出目录必须是同盘, 不支持跨卷, 如要跨卷可以尝试软链接模式. "
                    "另外, Mac 平台非本地磁盘不支持创建硬链接, 请选择软链接模式. "
                    f"\n{str(e)}"
                )
            else:
                LogBuffer.log().write(
                    f"\n 🔴 创建硬链接失败. "
                    f"硬链接要求待刮削文件和输出目录必须是同盘, 不支持跨卷. "
                    f"如要跨卷可以尝试软链接模式.\n{str(e)} "
                )
            LogBuffer.error().write("创建硬链接失败")
            signal.show_traceback_log(traceback.format_exc())
            signal.show_log_text(traceback.format_exc())
            return False

    # 其他情况，就移动文件
    result, error_info = await move_file_async(file_path, file_new_path)
    if result:
        LogBuffer.log().write(f"\n 🍀 Movie done! \n 🙉 [Movie] {file_new_path}")
        if await aiofiles.os.path.islink(file_new_path):
            LogBuffer.log().write(f"\n    此文件是软链接. 源文件: {file_new_path.resolve()}")
        file_info.file_path = file_new_path
        return True
    else:
        if "are the same file" in error_info.lower():  # 大小写不同，win10 用raidrive 挂载 google drive 改名会出错
            if file_info.cd_part:
                temp_folder, temp_file = split_path(str(file_new_path))
                if temp_file not in await aiofiles.os.listdir(temp_folder):
                    await move_file_async(str(file_path), str(file_new_path) + ".MDCx.tmp")
                    await move_file_async(str(file_new_path) + ".MDCx.tmp", str(file_new_path))
            LogBuffer.log().write(f"\n 🍀 Movie done! \n 🙉 [Movie] {file_new_path}")
            file_info.file_path = file_new_path
            return True
        LogBuffer.log().write(f"\n 🔴 移动视频文件到成功文件夹失败!\n    {error_info}")
        return False


def _get_folder_path(success_folder: Path, file_info: FileInfo, res: CrawlersResult) -> tuple[Path, str]:
    folder_name: str = manager.config.folder_name.replace("\\", "/")  # 设置-命名-视频目录名
    folder_path = file_info.file_path.parent

    # 更新模式 或 读取模式
    if manager.config.main_mode == 3 or manager.config.main_mode == 4:
        if manager.config.update_mode == "c":
            folder_name = folder_path.name
            return folder_path, folder_name
        elif "bc" in manager.config.update_mode:
            folder_name = manager.config.update_b_folder
            success_folder = folder_path.parent
            if "a" in manager.config.update_mode:
                success_folder = success_folder.parent
                folder_name = (
                    str(Path(manager.config.update_a_folder) / manager.config.update_b_folder)
                    .replace("\\", "/")
                    .strip("/")
                )
        elif manager.config.update_mode == "d":
            folder_name = manager.config.update_d_folder
            success_folder = folder_path

    # 正常模式 或 整理模式
    else:
        # 关闭软链接，并且成功后移动文件关时，使用原来文件夹
        if manager.config.soft_link == 0 and not manager.config.success_file_move:
            return folder_path, folder_name

    # 当根据刮削模式得到的视频目录名为空时，使用成功输出目录
    if not folder_name:
        return success_folder, ""

    show_4k = manager.config.folder_hd
    show_cnword = manager.config.folder_cnword
    show_moword = manager.config.folder_moword
    should_escape_result = True
    folder_new_name, folder_name, number, originaltitle, outline, title = render_name_template(
        folder_name,
        file_info,
        res,
        show_4k,
        show_cnword,
        show_moword,
        should_escape_result,
    )

    # 去除各种乱七八糟字符后，文件夹名为空时，使用number显示
    folder_name_temp = re.sub(r'[\\/:*?"<>|\r\n]+', "", folder_new_name)
    folder_name_temp = folder_name_temp.replace("//", "/").replace("--", "-").strip("-")
    if not folder_name_temp:
        folder_new_name = number

    # 判断文件夹名长度，超出长度时，截短标题名
    folder_name_max = int(manager.config.folder_name_max)
    if len(folder_new_name) > folder_name_max:
        cut_index = folder_name_max - len(folder_new_name)
        if "originaltitle" in folder_name:
            LogBuffer.log().write(
                f"\n 💡 当前目录名长度：{len(folder_new_name)}，最大允许长度：{folder_name_max}，目录命名时将去除原标题后{abs(cut_index)}个字符!"
            )
            folder_new_name = folder_new_name.replace(originaltitle, originaltitle[0:cut_index])
        elif "title" in folder_name:
            LogBuffer.log().write(
                f"\n 💡 当前目录名长度：{len(folder_new_name)}，最大允许长度：{folder_name_max}，目录命名时将去除标题后{abs(cut_index)}个字符!"
            )
            folder_new_name = folder_new_name.replace(title, title[0:cut_index])
        elif "outline" in folder_name:
            LogBuffer.log().write(
                f"\n 💡 当前目录名长度：{len(folder_new_name)}，最大允许长度：{folder_name_max}，目录命名时将去除简介后{abs(cut_index)}个字符!"
            )
            folder_new_name = folder_new_name.replace(outline, outline[0:cut_index])

    # 替换一些字符
    folder_new_name = folder_new_name.replace("--", "-").strip("-").strip("- .")

    # 用在保存文件时的名字，需要过滤window异常字符 特殊字符
    folder_new_name = re.sub(r'[\\:*?"<>|\r\n]+', "", folder_new_name).strip(" /")

    # 过滤文件夹名字前后的空格
    folder_new_name = folder_new_name.replace(" /", "/").replace(" \\", "\\").replace("/ ", "/").replace("\\ ", "\\")

    # 日文浊音转换（mac的坑,osx10.12以下使用nfd）
    folder_new_name = nfd2c(folder_new_name)

    return success_folder / folder_new_name, folder_new_name


def _generate_file_name(cd_part, file_info: FileInfo, res: CrawlersResult) -> str:
    file_path = file_info.file_path
    file_full_name = split_path(file_path)[1]
    file_name, file_ex = os.path.splitext(file_full_name)

    # 如果成功后不重命名，则返回原来名字
    if not manager.config.success_file_rename:
        return file_name

    # 更新模式 或 读取模式
    if manager.config.main_mode == 3 or manager.config.main_mode == 4:
        file_name_template = manager.config.update_c_filetemplate
    # 正常模式 或 整理模式
    else:
        file_name_template = manager.config.naming_file

    # 获取文件信息
    show_4k = manager.config.file_hd
    show_cnword = manager.config.file_cnword
    show_moword = manager.config.file_moword
    should_escape_result = True
    file_name, file_name_template, number, originaltitle, outline, title = render_name_template(
        file_name_template,
        file_info,
        res,
        show_4k,
        show_cnword,
        show_moword,
        should_escape_result,
    )

    file_name += cd_part

    # 去除各种乱七八糟字符后，文件名为空时，使用number显示
    file_name_temp = re.sub(r'[\\/:*?"<>|\r\n]+', "", file_name)
    file_name_temp = file_name_temp.replace("//", "/").replace("--", "-").strip("-")
    if not file_name_temp:
        file_name = number

    # 插入防屏蔽字符（115）
    prevent_char = manager.config.prevent_char
    if prevent_char:
        file_char_list = list(file_name)
        file_name = prevent_char.join(file_char_list)

    # 判断文件名长度，超出长度时，截短文件名
    file_name_max = int(manager.config.file_name_max)
    if len(file_name) > file_name_max:
        cut_index = file_name_max - len(file_name) - len(file_ex)

        # 如果没有防屏蔽字符，截短标题或者简介，这样不影响其他字段阅读
        if not prevent_char:
            if "originaltitle" in file_name_template:
                LogBuffer.log().write(
                    f"\n 💡 当前文件名长度：{len(file_name)}，最大允许长度：{file_name_max}，文件命名时将去除原标题后{abs(cut_index)}个字符!"
                )
                file_name = file_name.replace(originaltitle, originaltitle[:cut_index])
            elif "title" in file_name_template:
                LogBuffer.log().write(
                    f"\n 💡 当前文件名长度：{len(file_name)}，最大允许长度：{file_name_max}，文件命名时将去除标题后{abs(cut_index)}个字符!"
                )
                file_name = file_name.replace(title, title[:cut_index])
            elif "outline" in file_name_template:
                LogBuffer.log().write(
                    f"\n 💡 当前文件名长度：{len(file_name)}，最大允许长度：{file_name_max}，文件命名时将去除简介后{abs(cut_index)}个字符!"
                )
                file_name = file_name.replace(outline, outline[:cut_index])

        # 加了防屏蔽字符，直接截短
        else:
            file_name = file_name[:cut_index]

    # 替换一些字符
    file_name = file_name.replace("//", "/").replace("--", "-").strip("-")

    # 用在保存文件时的名字，需要过滤window异常字符 特殊字符
    file_name = re.sub(r'[\\/:*?"<>|\r\n]+', "", file_name).strip()

    # 过滤文件名字前后的空格
    file_name = file_name.replace(" /", "/").replace(" \\", "\\").replace("/ ", "/").replace("\\ ", "\\").strip()

    # 日文浊音转换（mac的坑,osx10.12以下使用nfd）
    file_name = nfd2c(file_name)

    return file_name


def get_output_name(
    file_info: FileInfo, json_data: CrawlersResult, success_folder: Path, file_ex: str
) -> tuple[Path, Path, Path, Path, Path, Path, str, Path, Path, Path]:
    # =====================================================================================更新输出文件夹名
    folder_new_path, folder_name = _get_folder_path(success_folder, file_info, json_data)
    # =====================================================================================更新实体文件命名规则
    naming_rule = _generate_file_name(file_info.cd_part, file_info, json_data)
    # =====================================================================================生成文件和nfo新路径
    file_new_name = naming_rule + file_ex.lower()
    nfo_new_name = naming_rule + ".nfo"
    file_new_path = folder_new_path / file_new_name
    nfo_new_path = folder_new_path / nfo_new_name
    # =====================================================================================生成图片下载路径
    poster_new_name = naming_rule + "-poster.jpg"
    thumb_new_name = naming_rule + "-thumb.jpg"
    fanart_new_name = naming_rule + "-fanart.jpg"
    poster_new_path_with_filename = folder_new_path / poster_new_name
    thumb_new_path_with_filename = folder_new_path / thumb_new_name
    fanart_new_path_with_filename = folder_new_path / fanart_new_name
    # =====================================================================================生成图片最终路径
    # 如果图片命名规则不加文件名并且视频目录不为空
    if manager.config.pic_simple_name and folder_name:
        poster_final_name = "poster.jpg"
        thumb_final_name = "thumb.jpg"
        fanart_final_name = "fanart.jpg"
    else:
        poster_final_name = naming_rule + "-poster.jpg"
        thumb_final_name = naming_rule + "-thumb.jpg"
        fanart_final_name = naming_rule + "-fanart.jpg"
    poster_final_path = folder_new_path / poster_final_name
    thumb_final_path = folder_new_path / thumb_final_name
    fanart_final_path = folder_new_path / fanart_final_name

    return (
        folder_new_path,
        file_new_path,
        nfo_new_path,
        poster_new_path_with_filename,
        thumb_new_path_with_filename,
        fanart_new_path_with_filename,
        naming_rule,
        poster_final_path,
        thumb_final_path,
        fanart_final_path,
    )


async def get_file_info_v2(file_path: Path, copy_sub: bool = True) -> FileInfo:
    optional_data = {}
    movie_number = ""
    has_sub = False
    c_word = ""
    cd_part = ""
    destroyed = ""
    leak = ""
    wuma = ""
    youma = ""
    mosaic = ""
    sub_list = []
    cnword_style = manager.config.cnword_style
    if Flags.file_mode == FileMode.Again and file_path in Flags.new_again_dic:
        temp_number, temp_url, temp_website = Flags.new_again_dic[file_path]
        if temp_number:  # 如果指定了番号，则使用指定番号
            movie_number = temp_number
            optional_data["appoint_number"] = temp_number
        if temp_url:
            optional_data["appoint_url"] = temp_url
            optional_data["website_name"] = temp_website
    elif Flags.file_mode == FileMode.Single:  # 刮削单文件（工具页面）
        optional_data["appoint_url"] = Flags.appoint_url

    # 获取显示路径
    file_path_str = str(file_path).replace("\\", "/")
    file_show_path = showFilePath(file_path_str)

    # 获取文件名
    folder_path, file_full_name = split_path(file_path)  # 获取去掉文件名的路径、完整文件名（含扩展名）
    file_name, file_ex = os.path.splitext(file_full_name)  # 获取文件名（不含扩展名）、扩展名(含有.)
    file_name_temp = file_name + "."
    nfo_old_name = file_name + ".nfo"
    nfo_old_path = folder_path / nfo_old_name
    file_show_name = file_name

    # 软链接时，获取原身路径(用来查询原身文件目录是否有字幕)
    file_ori_path = None
    if await aiofiles.os.path.islink(file_path):
        file_ori_path = file_path.resolve()
    try:
        # 清除防屏蔽字符
        prevent_char = manager.config.prevent_char
        if prevent_char:
            file_path_str = str(file_path).replace(prevent_char, "")
            file_name = file_name.replace(prevent_char, "")

        # 获取番号
        if not movie_number:
            movie_number = get_file_number(file_path_str, manager.computed.escape_string_list)

        # 259LUXU-1111, 非mgstage、avsex去除前面的数字前缀
        temp_n = re.findall(r"\d{3,}([a-zA-Z]+\d*-\d+)", movie_number)
        optional_data["short_number"] = temp_n[0] if temp_n else ""

        # 去掉各种乱七八糟的字符
        file_name_cd = remove_escape_string(file_name, "-").replace(movie_number, "-").replace("--", "-").strip()

        # 替换分隔符为-
        cd_char = manager.config.cd_char
        if CDChar.UNDERLINE in cd_char:
            file_name_cd = file_name_cd.replace("_", "-")
        if CDChar.SPACE in cd_char:
            file_name_cd = file_name_cd.replace(" ", "-")
        if CDChar.POINT in cd_char:
            file_name_cd = file_name_cd.replace(".", "-")
        file_name_cd = file_name_cd.lower() + "."  # .作为结尾

        # 获取分集(排除‘番号-C’和‘番号C’作为字幕标识的情况)
        # if '-C' in config.cnword_char:
        #     file_name_cd = file_name_cd.replace('-c.', '.')
        # else:
        #     file_name_cd = file_name_cd.replace('-c.', '-cd3.')
        # if 'C.' in config.cnword_char and file_name_cd.endswith('c.'):
        #     file_name_cd = file_name_cd[:-2] + '.'

        temp_cd = re.compile(r"(vol|case|no|cwp|cwpbd|act)[-\.]?\d+")
        temp_cd_filename = re.sub(temp_cd, "", file_name_cd)
        cd_path_1 = re.findall(r"[-_ .]{1}(cd|part|hd)([0-9]{1,2})", temp_cd_filename)
        cd_path_2 = re.findall(r"-([0-9]{1,2})\.?$", temp_cd_filename)
        cd_path_3 = re.findall(r"(-|\d{2,}|\.)([a-o]{1})\.?$", temp_cd_filename)
        cd_path_4 = re.findall(r"-([0-9]{1})[^a-z0-9]", temp_cd_filename)
        if cd_path_1 and int(cd_path_1[0][1]) > 0:
            cd_part = cd_path_1[0][1]
        elif cd_path_2:
            if len(cd_path_2[0]) == 1 or CDChar.DIGITAL in cd_char:
                cd_part = str(int(cd_path_2[0]))
        elif cd_path_3 and CDChar.LETTER in cd_char:
            letter_list = [
                "",
                "a",
                "b",
                "c",
                "d",
                "e",
                "f",
                "g",
                "h",
                "i",
                "j",
                "k",
                "l",
                "m",
                "n",
                "o",
                "p",
                "q",
                "r",
                "s",
                "t",
                "u",
                "v",
                "w",
                "x",
                "y",
                "z",
            ]
            if cd_path_3[0][1] != "c" or CDChar.ENDC in cd_char:
                cd_part = str(letter_list.index(cd_path_3[0][1]))
        elif cd_path_4 and CDChar.MIDDLE_NUMBER in cd_char:
            cd_part = str(int(cd_path_4[0]))

        # 判断分集命名规则
        if cd_part:
            cd_name = manager.config.cd_name
            if int(cd_part) == 0:
                cd_part = ""
            elif cd_name == 0:
                cd_part = "-cd" + str(cd_part)
            elif cd_name == 1:
                cd_part = "-CD" + str(cd_part)
            else:
                cd_part = "-" + str(cd_part)

        # 判断是否是马赛克破坏版
        umr_style = str(manager.config.umr_style)
        if (
            "-uncensored." in file_path_str.lower()
            or "umr." in file_path_str.lower()
            or "破解" in file_path_str
            or "克破" in file_path_str
            or (umr_style and umr_style in file_path_str)
            or "-u." in file_path_str.lower()
            or "-uc." in file_path_str.lower()
        ):
            destroyed = umr_style
            mosaic = "无码破解"

        # 判断是否国产
        if not mosaic:
            if "国产" in file_path_str or "麻豆" in file_path_str or "國產" in file_path_str:
                mosaic = "国产"
            else:
                md_list = [
                    "国产",
                    "國產",
                    "麻豆",
                    "传媒",
                    "傳媒",
                    "皇家华人",
                    "皇家華人",
                    "精东",
                    "精東",
                    "猫爪影像",
                    "貓爪影像",
                    "91CM",
                    "91MS",
                    "导演系列",
                    "導演系列",
                    "MDWP",
                    "MMZ",
                    "MLT",
                    "MSM",
                    "LAA",
                    "MXJ",
                    "SWAG",
                ]
                for each in md_list:
                    if each in file_path_str:
                        mosaic = "国产"

        # 判断是否流出
        leak_style = str(manager.config.leak_style)
        if not mosaic and (
            "流出" in file_path_str or "leaked" in file_path_str.lower() or (leak_style and leak_style in file_path_str)
        ):
            leak = leak_style
            mosaic = "无码流出"

        # 判断是否无码
        wuma_style = str(manager.config.wuma_style)
        if not mosaic and (
            "无码" in file_path_str
            or "無碼" in file_path_str
            or "無修正" in file_path_str
            or "uncensored" in file_path_str.lower()
            or is_uncensored(movie_number)
        ):
            wuma = wuma_style
            mosaic = "无码"

        # 判断是否有码
        youma_style = manager.config.youma_style
        if not mosaic and ("有码" in file_path_str or "有碼" in file_path_str):
            youma = youma_style
            mosaic = "有码"

        # 查找本地字幕文件
        cnword_list = manager.config.cnword_char
        cnword_list = [x for x in cnword_list if x]  # 强制去空值
        if "-C." in str(cnword_list).upper():
            cnword_list.append("-C ")
        sub_type_list = manager.config.sub_type  # 本地字幕后缀
        for sub_type in sub_type_list:  # 查找本地字幕, 可能多个
            sub_type_chs = ".chs" + sub_type
            sub_path_chs = folder_path / (file_name + sub_type_chs)
            sub_path = folder_path / (file_name + sub_type)
            if await aiofiles.os.path.exists(sub_path_chs):
                sub_list.append(sub_type_chs)
                c_word = cnword_style  # 中文字幕影片后缀
                has_sub = True
            if await aiofiles.os.path.exists(sub_path):
                sub_list.append(sub_type)
                c_word = cnword_style  # 中文字幕影片后缀
                has_sub = True
            if file_ori_path:  # 原身路径
                sub_path2 = file_ori_path.with_suffix(sub_type)
                if await aiofiles.os.path.exists(sub_path2):
                    c_word = cnword_style  # 中文字幕影片后缀
                    has_sub = True

        # 判断路径名是否有中文字幕字符
        if not has_sub:
            cnword_list.append("-uc.")
            file_name_temp = file_name_temp.upper().replace("CD", "").replace("CARIB", "")  # 去掉cd/carib，避免-c误判
            if CDChar.LETTER in cd_char and CDChar.ENDC in cd_char:
                file_name_temp = re.sub(r"(-|\d{2,}|\.)C\.$", ".", file_name_temp)

            for each in cnword_list:
                if each.upper() in file_name_temp and "無字幕" not in file_path_str and "无字幕" not in file_path_str:
                    c_word = cnword_style  # 中文字幕影片后缀
                    has_sub = True
                    break

        # 判断nfo中是否有中文字幕、马赛克
        if (not has_sub or not mosaic) and await aiofiles.os.path.exists(nfo_old_path):
            try:
                async with aiofiles.open(nfo_old_path, encoding="utf-8") as f:
                    nfo_content = await f.read()
                if not has_sub and ">中文字幕</" in nfo_content:
                    c_word = cnword_style  # 中文字幕影片后缀
                    has_sub = True
                if not mosaic:
                    if ">无码流出</" in nfo_content or ">無碼流出</" in nfo_content:
                        leak = leak_style
                        mosaic = "无码流出"
                    elif ">无码破解</" in nfo_content or ">無碼破解</" in nfo_content:
                        destroyed = umr_style
                        mosaic = "无码破解"
                    elif ">无码</" in nfo_content or ">無碼</" in nfo_content:
                        wuma = wuma_style
                        mosaic = "无码"
                    elif ">有碼</" in nfo_content or ">有碼</" in nfo_content:
                        youma = youma_style
                        mosaic = "有码"
                    elif ">国产</" in nfo_content or ">國產</" in nfo_content:
                        youma = youma_style
                        mosaic = "国产"
                    elif ">里番</" in nfo_content or ">裏番</" in nfo_content:
                        youma = youma_style
                        mosaic = "里番"
                    elif ">动漫</" in nfo_content or ">動漫</" in nfo_content:
                        youma = youma_style
                        mosaic = "动漫"
            except Exception:
                signal.show_traceback_log(traceback.format_exc())

        if not has_sub and await aiofiles.os.path.exists(nfo_old_path):
            try:
                async with aiofiles.open(nfo_old_path, encoding="utf-8") as f:
                    nfo_content = await f.read()
                if "<genre>中文字幕</genre>" in nfo_content or "<tag>中文字幕</tag>" in nfo_content:
                    c_word = cnword_style  # 中文字幕影片后缀
                    has_sub = True
            except Exception:
                signal.show_traceback_log(traceback.format_exc())

        # 查找字幕包目录字幕文件
        subtitle_add = manager.config.subtitle_add
        if not has_sub and copy_sub and subtitle_add:
            subtitle_folder = manager.config.subtitle_folder
            subtitle_add = manager.config.subtitle_add
            if subtitle_add and subtitle_folder:  # 复制字幕开
                for sub_type in sub_type_list:
                    sub_path_1 = os.path.join(subtitle_folder, (movie_number + cd_part + sub_type))
                    sub_path_2 = os.path.join(subtitle_folder, file_name + sub_type)
                    sub_file_name = file_name + sub_type
                    if manager.config.subtitle_add_chs:
                        sub_file_name = file_name + ".chs" + sub_type
                        sub_type = ".chs" + sub_type
                    sub_new_path = folder_path / sub_file_name
                    for sub_path in (sub_path_1, sub_path_2):
                        if await aiofiles.os.path.exists(sub_path):
                            await copy_file_async(sub_path, sub_new_path)
                            LogBuffer.log().write(f"\n\n 🍉 Sub file '{sub_file_name}' copied successfully! ")
                            sub_list.append(sub_type)
                            c_word = cnword_style  # 中文字幕影片后缀
                            has_sub = True
                            break

        file_show_name = movie_number
        suffix_sort_list = manager.config.suffix_sort
        for each in suffix_sort_list:
            if each == "moword":
                file_show_name += destroyed + leak + wuma + youma
            elif each == "cnword":
                file_show_name += c_word
        file_show_name += cd_part

    except Exception:
        signal.show_traceback_log(file_path)
        signal.show_traceback_log(traceback.format_exc())
        signal.show_log_text(traceback.format_exc())
        LogBuffer.log().write("\n" + str(file_path))
        LogBuffer.log().write("\n" + traceback.format_exc())

    return FileInfo(
        number=movie_number,
        letters=get_number_letters(movie_number),
        has_sub=has_sub,
        c_word=c_word,
        cd_part=cd_part,
        destroyed=destroyed,
        leak=leak,
        wuma=wuma,
        youma=youma,
        mosaic=mosaic,
        file_path=Path(file_path),
        folder_path=folder_path,
        file_name=file_name,
        file_ex=file_ex,
        sub_list=sub_list,
        file_show_name=file_show_name,
        file_show_path=Path(file_show_path),
        short_number=optional_data.get("short_number", ""),
        appoint_number=optional_data.get("appoint_number", ""),
        appoint_url=optional_data.get("appoint_url", ""),
        website_name=optional_data.get("website_name", ""),
        definition="",
        codec="",
    )


async def deal_old_files(
    number: str,
    info: OtherInfo,
    folder_old_path: Path,
    folder_new_path: Path,
    file_path: Path,
    # file_new_path: Path,
    thumb_new_path_with_filename: Path,
    poster_new_path_with_filename: Path,
    fanart_new_path_with_filename: Path,
    nfo_new_path: Path,
    # file_ex: str,
    poster_final_path: Path,
    thumb_final_path: Path,
    fanart_final_path: Path,
) -> tuple[bool, bool]:
    """
    处理本地已存在的thumb、poster、fanart、nfo
    """
    nfo_old_path = file_path.with_suffix(".nfo")
    file_name = file_path.stem
    extrafanart_old_path = folder_old_path / "extrafanart"
    extrafanart_new_path = folder_new_path / "extrafanart"
    extrafanart_folder = manager.config.extrafanart_folder
    extrafanart_copy_old_path = folder_old_path / extrafanart_folder
    extrafanart_copy_new_path = folder_new_path / extrafanart_folder
    trailer_name = manager.config.trailer_simple_name
    trailer_old_folder_path = folder_old_path / "trailers"
    trailer_new_folder_path = folder_new_path / "trailers"
    trailer_old_file_path = trailer_old_folder_path / "trailer.mp4"
    trailer_new_file_path = trailer_new_folder_path / "trailer.mp4"
    trailer_old_file_path_with_filename = nfo_old_path.with_name(f"{file_name}-trailer.mp4")
    trailer_new_file_path_with_filename = nfo_new_path.with_name(f"{file_name}-trailer.mp4")
    theme_videos_old_path = folder_old_path / "backdrops"
    theme_videos_new_path = folder_new_path / "backdrops"
    extrafanart_extra_old_path = folder_old_path / "behind the scenes"
    extrafanart_extra_new_path = folder_new_path / "behind the scenes"

    # 图片旧路径转换路径
    poster_old_path_with_filename = file_path.with_name(f"{file_name}-poster.jpg")
    thumb_old_path_with_filename = file_path.with_name(f"{file_name}-thumb.jpg")
    fanart_old_path_with_filename = file_path.with_name(f"{file_name}-fanart.jpg")
    poster_old_path_no_filename = folder_old_path / "poster.jpg"
    thumb_old_path_no_filename = folder_old_path / "thumb.jpg"
    fanart_old_path_no_filename = folder_old_path / "fanart.jpg"
    file_path_list = {
        nfo_old_path,
        nfo_new_path,
        thumb_old_path_with_filename,
        thumb_old_path_no_filename,
        thumb_new_path_with_filename,
        thumb_final_path,
        poster_old_path_with_filename,
        poster_old_path_no_filename,
        poster_new_path_with_filename,
        poster_final_path,
        fanart_old_path_with_filename,
        fanart_old_path_no_filename,
        fanart_new_path_with_filename,
        fanart_final_path,
        trailer_old_file_path_with_filename,
        trailer_new_file_path_with_filename,
    }
    folder_path_list = {
        extrafanart_old_path,
        extrafanart_new_path,
        extrafanart_copy_old_path,
        extrafanart_copy_new_path,
        trailer_old_folder_path,
        trailer_new_folder_path,
        theme_videos_old_path,
        theme_videos_new_path,
        extrafanart_extra_old_path,
        extrafanart_extra_new_path,
    }

    # 视频模式进行清理
    main_mode = manager.config.main_mode
    if main_mode == 2 and Switch.SORT_DEL in manager.config.switch_on:
        for each in file_path_list:
            if await aiofiles.os.path.exists(each):
                await delete_file_async(each)
        for each in folder_path_list:
            if await aiofiles.os.path.isdir(each):
                shutil.rmtree(each, ignore_errors=True)
        return False, False

    # 非视频模式，将本地已有的图片、剧照等文件，按照命名规则，重新命名和移动。这个环节仅应用设置-命名设置，没有应用设置-下载的设置
    # 抢占图片的处理权
    single_folder_catched = False  # 剧照、剧照副本、主题视频 这些单文件夹的处理权，他们只需要处理一次
    pic_final_catched = False  # 最终图片（poster、thumb、fanart）的处理权
    if thumb_new_path_with_filename not in Flags.pic_catch_set:
        if thumb_final_path != thumb_new_path_with_filename:
            if thumb_final_path not in Flags.pic_catch_set:  # 不带文件名的图片的下载权利（下载权利只给它一个）
                Flags.pic_catch_set.add(thumb_final_path)
                pic_final_catched = True
        else:
            pic_final_catched = True  # 带文件名的图片，下载权利给每一个。（如果有一个下载好了，未下载的可以直接复制）
    # 处理 extrafanart、extrafanart副本、主题视频、附加视频
    if pic_final_catched and extrafanart_new_path not in Flags.extrafanart_deal_set:
        Flags.extrafanart_deal_set.add(extrafanart_new_path)
        single_folder_catched = True
    """
    需要考虑旧文件分集情况（带文件名、不带文件名）、旧文件不同扩展名情况，他们如何清理或保留
    需要考虑新文件分集情况（带文件名、不带文件名）
    需要考虑分集同时刮削如何节省流量
    需要考虑分集带文件名图片是否会有重复水印问题
    """

    # poster_marked True 不加水印，避免二次加水印,；poster_exists 是不是存在本地图片
    info.poster_marked = True
    info.thumb_marked = True
    info.fanart_marked = True
    poster_exists = True
    thumb_exists = True
    fanart_exists = True
    trailer_exists = True

    # 软硬链接模式，不处理旧的图片
    if manager.config.soft_link != 0:
        return pic_final_catched, single_folder_catched

    """
    保留图片或删除图片说明：
    图片保留的前提条件：非整理模式，并且满足（在保留名单 或 读取模式 或 图片已下载）。此时不清理 poster.jpg thumb.jpg fanart.jpg（在del_noname_pic中清理）。
    图片保留的命名方式：保留时会保留为最终路径 和 文件名-thumb.jpg (thumb 需要复制一份为 文件名-thumb.jpg，避免 poster 没有，要用 thumb 裁剪，或者 fanart 要复制 thumb)
    图片下载的命名方式：新下载的则都保存为 文件名-thumb.jpg（因为多分集同时下载为 thumb.jpg 时会冲突）
    图片下载的下载条件：如果最终路径有内容，则不下载。如果 文件名-thumb.jpg 有内容，也不下载。
    图片下载的复制条件：如果不存在 文件名-thumb.jpg，但是存在 thumb.jpg，则复制 thumb.jpg 为 文件名-thumb.jpg
    最终的图片处理：在最终的 rename pic 环节，如果最终路径有内容，则删除非最终路径的内容；如果最终路径没内容，表示图片是刚下载的，要改成最终路径。
    """

    # poster 处理：寻找对应文件放到最终路径上。这样避免刮削失败时，旧的图片被删除
    done_poster_path = Flags.file_done_dic.get(number, {}).get("poster")
    done_poster_path_copy = True
    try:
        # 图片最终路径等于已下载路径时，图片是已下载的，不需要处理
        if (
            done_poster_path
            and await aiofiles.os.path.exists(done_poster_path)
            and split_path(done_poster_path)[0] == split_path(poster_final_path)[0]
        ):  # 如果存在已下载完成的文件，尝试复制
            done_poster_path_copy = False  # 标记未复制！此处不复制，在poster download中复制
        elif await aiofiles.os.path.exists(poster_final_path):
            pass  # windows、mac大小写不敏感，暂不解决
        elif poster_new_path_with_filename != poster_final_path and await aiofiles.os.path.exists(
            poster_new_path_with_filename
        ):
            await move_file_async(poster_new_path_with_filename, poster_final_path)
        elif poster_old_path_with_filename != poster_final_path and await aiofiles.os.path.exists(
            poster_old_path_with_filename
        ):
            await move_file_async(poster_old_path_with_filename, poster_final_path)
        elif poster_old_path_no_filename != poster_final_path and await aiofiles.os.path.exists(
            poster_old_path_no_filename
        ):
            await move_file_async(poster_old_path_no_filename, poster_final_path)
        else:
            poster_exists = False

        if poster_exists:
            Flags.file_done_dic[number].update({"local_poster": poster_final_path})
            # 清理旧图片
            if poster_old_path_with_filename != poster_final_path and await aiofiles.os.path.exists(
                poster_old_path_with_filename
            ):
                await delete_file_async(poster_old_path_with_filename)
            if str(poster_old_path_no_filename).lower() != str(
                poster_final_path
            ).lower() and await aiofiles.os.path.exists(poster_old_path_no_filename):
                await delete_file_async(poster_old_path_no_filename)
            if str(poster_new_path_with_filename).lower() != str(
                poster_final_path
            ).lower() and await aiofiles.os.path.exists(poster_new_path_with_filename):
                await delete_file_async(poster_new_path_with_filename)
        elif p := Flags.file_done_dic[number]["local_poster"]:
            await copy_file_async(p, poster_final_path)

    except Exception:
        signal.show_log_text(traceback.format_exc())

    # thumb 处理：寻找对应文件放到最终路径上。这样避免刮削失败时，旧的图片被删除
    done_thumb_path = Flags.file_done_dic.get(number, {}).get("thumb")
    done_thumb_path_copy = True
    try:
        # 图片最终路径等于已下载路径时，图片是已下载的，不需要处理
        if (
            done_thumb_path
            and await aiofiles.os.path.exists(done_thumb_path)
            and split_path(done_thumb_path)[0] == split_path(thumb_final_path)[0]
        ):
            done_thumb_path_copy = False  # 标记未复制！此处不复制，在 thumb download中复制
        elif await aiofiles.os.path.exists(thumb_final_path):
            pass
        elif thumb_new_path_with_filename != thumb_final_path and await aiofiles.os.path.exists(
            thumb_new_path_with_filename
        ):
            await move_file_async(thumb_new_path_with_filename, thumb_final_path)
        elif thumb_old_path_with_filename != thumb_final_path and await aiofiles.os.path.exists(
            thumb_old_path_with_filename
        ):
            await move_file_async(thumb_old_path_with_filename, thumb_final_path)
        elif thumb_old_path_no_filename != thumb_final_path and await aiofiles.os.path.exists(
            thumb_old_path_no_filename
        ):
            await move_file_async(thumb_old_path_no_filename, thumb_final_path)
        else:
            thumb_exists = False

        if thumb_exists:
            Flags.file_done_dic[number].update({"local_thumb": thumb_final_path})
            # 清理旧图片
            if str(thumb_old_path_with_filename).lower() != str(
                thumb_final_path
            ).lower() and await aiofiles.os.path.exists(thumb_old_path_with_filename):
                await delete_file_async(thumb_old_path_with_filename)
            if str(thumb_old_path_no_filename).lower() != str(
                thumb_final_path
            ).lower() and await aiofiles.os.path.exists(thumb_old_path_no_filename):
                await delete_file_async(thumb_old_path_no_filename)
            if str(thumb_new_path_with_filename).lower() != str(
                thumb_final_path
            ).lower() and await aiofiles.os.path.exists(thumb_new_path_with_filename):
                await delete_file_async(thumb_new_path_with_filename)
        elif p := Flags.file_done_dic[number]["local_thumb"]:
            await copy_file_async(p, thumb_final_path)

    except Exception:
        signal.show_log_text(traceback.format_exc())

    # fanart 处理：寻找对应文件放到最终路径上。这样避免刮削失败时，旧的图片被删除
    done_fanart_path = Flags.file_done_dic.get(number, {}).get("fanart")
    done_fanart_path_copy = True
    try:
        # 图片最终路径等于已下载路径时，图片是已下载的，不需要处理
        if (
            done_fanart_path
            and await aiofiles.os.path.exists(done_fanart_path)
            and split_path(done_fanart_path)[0] == split_path(fanart_final_path)[0]
        ):
            done_fanart_path_copy = False  # 标记未复制！此处不复制，在 fanart download中复制
        elif await aiofiles.os.path.exists(fanart_final_path):
            pass
        elif fanart_new_path_with_filename != fanart_final_path and await aiofiles.os.path.exists(
            fanart_new_path_with_filename
        ):
            await move_file_async(fanart_new_path_with_filename, fanart_final_path)
        elif fanart_old_path_with_filename != fanart_final_path and await aiofiles.os.path.exists(
            fanart_old_path_with_filename
        ):
            await move_file_async(fanart_old_path_with_filename, fanart_final_path)
        elif fanart_old_path_no_filename != fanart_final_path and await aiofiles.os.path.exists(
            fanart_old_path_no_filename
        ):
            await move_file_async(fanart_old_path_no_filename, fanart_final_path)
        else:
            fanart_exists = False

        if fanart_exists:
            Flags.file_done_dic[number].update({"local_fanart": fanart_final_path})
            # 清理旧图片
            if fanart_old_path_with_filename != fanart_final_path and await aiofiles.os.path.exists(
                fanart_old_path_with_filename
            ):
                await delete_file_async(fanart_old_path_with_filename)
            if fanart_old_path_no_filename != fanart_final_path and await aiofiles.os.path.exists(
                fanart_old_path_no_filename
            ):
                await delete_file_async(fanart_old_path_no_filename)
            if fanart_new_path_with_filename != fanart_final_path and await aiofiles.os.path.exists(
                fanart_new_path_with_filename
            ):
                await delete_file_async(fanart_new_path_with_filename)
        elif p := Flags.file_done_dic[number]["local_fanart"]:
            await copy_file_async(p, fanart_final_path)

    except Exception:
        signal.show_log_text(traceback.format_exc())

    # 更新图片地址
    info.poster_path = poster_final_path if poster_exists and done_poster_path_copy else None
    info.thumb_path = thumb_final_path if thumb_exists and done_thumb_path_copy else None
    info.fanart_path = fanart_final_path if fanart_exists and done_fanart_path_copy else None

    # nfo 处理
    try:
        if await aiofiles.os.path.exists(nfo_new_path):
            if str(nfo_old_path).lower() != str(nfo_new_path).lower() and await aiofiles.os.path.exists(nfo_old_path):
                await delete_file_async(nfo_old_path)
        elif nfo_old_path != nfo_new_path and await aiofiles.os.path.exists(nfo_old_path):
            await move_file_async(nfo_old_path, nfo_new_path)
    except Exception:
        signal.show_log_text(traceback.format_exc())

    # trailer
    if trailer_name:  # 预告片名字不含视频文件名
        # trailer最终路径等于已下载路径时，trailer是已下载的，不需要处理
        if await aiofiles.os.path.exists(str(trailer_new_file_path)):
            if await aiofiles.os.path.exists(str(trailer_old_file_path_with_filename)):
                await delete_file_async(trailer_old_file_path_with_filename)
            elif await aiofiles.os.path.exists(str(trailer_new_file_path_with_filename)):
                await delete_file_async(trailer_new_file_path_with_filename)
        elif trailer_old_file_path != trailer_new_file_path and await aiofiles.os.path.exists(
            str(trailer_old_file_path)
        ):
            if not await aiofiles.os.path.exists(str(trailer_new_folder_path)):
                await aiofiles.os.makedirs(str(trailer_new_folder_path))
            await move_file_async(trailer_old_file_path, trailer_new_file_path)
        elif await aiofiles.os.path.exists(str(trailer_new_file_path_with_filename)):
            if not await aiofiles.os.path.exists(str(trailer_new_folder_path)):
                await aiofiles.os.makedirs(str(trailer_new_folder_path))
            await move_file_async(trailer_new_file_path_with_filename, trailer_new_file_path)
        elif await aiofiles.os.path.exists(str(trailer_old_file_path_with_filename)):
            if not await aiofiles.os.path.exists(str(trailer_new_folder_path)):
                await aiofiles.os.makedirs(str(trailer_new_folder_path))
            await move_file_async(trailer_old_file_path_with_filename, trailer_new_file_path)

        # 删除旧文件夹，用不到了
        if trailer_old_folder_path != trailer_new_folder_path and await aiofiles.os.path.exists(
            trailer_old_folder_path
        ):
            shutil.rmtree(trailer_old_folder_path, ignore_errors=True)
        # 删除带文件名文件，用不到了
        if await aiofiles.os.path.exists(trailer_old_file_path_with_filename):
            await delete_file_async(trailer_old_file_path_with_filename)
        if trailer_new_file_path_with_filename != trailer_old_file_path_with_filename and await aiofiles.os.path.exists(
            trailer_new_file_path_with_filename
        ):
            await delete_file_async(trailer_new_file_path_with_filename)
    else:
        # 目标文件带文件名
        if await aiofiles.os.path.exists(trailer_new_file_path_with_filename):
            if (
                trailer_old_file_path_with_filename != trailer_new_file_path_with_filename
                and await aiofiles.os.path.exists(trailer_old_file_path_with_filename)
            ):
                await delete_file_async(trailer_old_file_path_with_filename)
        elif (
            trailer_old_file_path_with_filename != trailer_new_file_path_with_filename
            and await aiofiles.os.path.exists(trailer_old_file_path_with_filename)
        ):
            await move_file_async(trailer_old_file_path_with_filename, trailer_new_file_path_with_filename)
        elif await aiofiles.os.path.exists(trailer_old_file_path):
            await move_file_async(trailer_old_file_path, trailer_new_file_path_with_filename)
        elif trailer_new_file_path != trailer_old_file_path and await aiofiles.os.path.exists(trailer_new_file_path):
            await move_file_async(trailer_new_file_path, trailer_new_file_path_with_filename)
        else:
            trailer_exists = False

        if trailer_exists:
            Flags.file_done_dic[number].update({"local_trailer": trailer_new_file_path_with_filename})
            # 删除旧、新文件夹，用不到了(分集使用local trailer复制即可)
            if await aiofiles.os.path.exists(trailer_old_folder_path):
                shutil.rmtree(trailer_old_folder_path, ignore_errors=True)
            if trailer_new_folder_path != trailer_old_folder_path and await aiofiles.os.path.exists(
                trailer_new_folder_path
            ):
                shutil.rmtree(trailer_new_folder_path, ignore_errors=True)
            # 删除带文件名旧文件，用不到了
            if (
                trailer_old_file_path_with_filename != trailer_new_file_path_with_filename
                and await aiofiles.os.path.exists(trailer_old_file_path_with_filename)
            ):
                await delete_file_async(trailer_old_file_path_with_filename)
        else:
            local_trailer = Flags.file_done_dic.get(number, {}).get("local_trailer")
            if local_trailer and await aiofiles.os.path.exists(local_trailer):
                await copy_file_async(local_trailer, trailer_new_file_path_with_filename)

    # 处理 extrafanart、extrafanart副本、主题视频、附加视频
    if single_folder_catched:
        # 处理 extrafanart
        try:
            if await aiofiles.os.path.exists(extrafanart_new_path):
                if str(extrafanart_old_path).lower() != str(
                    extrafanart_new_path
                ).lower() and await aiofiles.os.path.exists(extrafanart_old_path):
                    shutil.rmtree(extrafanart_old_path, ignore_errors=True)
            elif await aiofiles.os.path.exists(extrafanart_old_path):
                await move_file_async(extrafanart_old_path, extrafanart_new_path)
        except Exception:
            signal.show_log_text(traceback.format_exc())

        # extrafanart副本
        try:
            if await aiofiles.os.path.exists(extrafanart_copy_new_path):
                if str(extrafanart_copy_old_path).lower() != str(
                    extrafanart_copy_new_path
                ).lower() and await aiofiles.os.path.exists(extrafanart_copy_old_path):
                    shutil.rmtree(extrafanart_copy_old_path, ignore_errors=True)
            elif await aiofiles.os.path.exists(extrafanart_copy_old_path):
                await move_file_async(extrafanart_copy_old_path, extrafanart_copy_new_path)
        except Exception:
            signal.show_log_text(traceback.format_exc())

        # 主题视频
        if await aiofiles.os.path.exists(theme_videos_new_path):
            if str(theme_videos_old_path).lower() != str(
                theme_videos_new_path
            ).lower() and await aiofiles.os.path.exists(theme_videos_old_path):
                shutil.rmtree(theme_videos_old_path, ignore_errors=True)
        elif await aiofiles.os.path.exists(theme_videos_old_path):
            await move_file_async(theme_videos_old_path, theme_videos_new_path)

        # 附加视频
        if await aiofiles.os.path.exists(extrafanart_extra_new_path):
            if str(extrafanart_extra_old_path).lower() != str(
                extrafanart_extra_new_path
            ).lower() and await aiofiles.os.path.exists(extrafanart_extra_old_path):
                shutil.rmtree(extrafanart_extra_old_path, ignore_errors=True)
        elif await aiofiles.os.path.exists(extrafanart_extra_old_path):
            await move_file_async(extrafanart_extra_old_path, extrafanart_extra_new_path)

    return pic_final_catched, single_folder_catched
