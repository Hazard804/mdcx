import asyncio
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles.os
from PyQt6.QtWidgets import QMessageBox

from ..base.file import (
    _clean_empty_fodlers,
    check_file,
    copy_trailer_to_theme_videos,
    get_movie_list,
    move_bif,
    move_file_to_failed_folder,
    move_other_file,
    move_torrent,
    newtdisk_creat_symlink,
    pic_some_deal,
    save_success_list,
)
from ..base.image import extrafanart_copy2, extrafanart_extras_copy
from ..config.enums import DownloadableFile, EmbyAction, ReadMode, Switch
from ..config.extend import get_movie_path_setting
from ..config.manager import manager
from ..config.resources import resources
from ..crawler import CrawlerProvider
from ..models.enums import FileMode
from ..models.flags import FileDoneDict, Flags
from ..models.log_buffer import LogBuffer
from ..models.types import CrawlersResult, FileInfo, OtherInfo, ScrapeResult, ShowData
from ..signals import signal
from ..tools.emby_actor_image import update_emby_actor_photo
from ..tools.emby_actor_info import creat_kodi_actors
from ..utils import executor, get_current_time, get_real_time, get_used_time, split_path
from ..utils.dataclass import update
from ..utils.file import copy_file_async, move_file_async
from ..utils.path import is_descendant
from .file import creat_folder, deal_old_files, get_file_info_v2, get_output_name, move_movie
from .file_crawler import FileScraper
from .image import add_mark
from .nfo import get_nfo_data, write_nfo
from .translate import translate_actor, translate_info, translate_title_outline
from .utils import (
    add_definition_tag,
    deal_some_field,
    get_video_size,
    replace_special_word,
    replace_word,
    show_movie_info,
    show_result,
)
from .web import (
    extrafanart_download,
    fanart_download,
    poster_download,
    thumb_download,
    trailer_download,
)

if TYPE_CHECKING:
    from ..crawler import CrawlerProviderProtocol


class StopScrape(Exception): ...


class Scraper:
    def __init__(self, crawler_provider: "CrawlerProviderProtocol"):
        self.crawler_provider = crawler_provider

    async def _run_tasks_with_limit(self, movie_list: list[Path], task_count: int, thread_number: int) -> None:
        task_iter = iter(enumerate(movie_list, 1))
        running_tasks: set[asyncio.Task[None]] = set()

        def _submit_next_task() -> bool:
            try:
                index, each_file = next(task_iter)
            except StopIteration:
                return False
            running_tasks.add(asyncio.create_task(self.process_one_file((each_file, index, task_count))))
            return True

        for _ in range(min(thread_number, task_count)):
            _submit_next_task()

        try:
            while running_tasks:
                done, pending = await asyncio.wait(running_tasks, return_when=asyncio.FIRST_COMPLETED)
                running_tasks = set(pending)

                stop_requested = False
                fatal_error: Exception | None = None
                done_count = 0
                for done_task in done:
                    done_count += 1
                    try:
                        done_task.result()
                    except StopScrape:
                        stop_requested = True
                    except asyncio.CancelledError:
                        stop_requested = True
                    except Exception as e:
                        if fatal_error is None:
                            fatal_error = e

                if stop_requested or fatal_error is not None:
                    for pending_task in running_tasks:
                        pending_task.cancel()
                    if running_tasks:
                        await asyncio.gather(*running_tasks, return_exceptions=True)
                    if fatal_error is not None:
                        raise fatal_error
                    return

                for _ in range(done_count):
                    _submit_next_task()
        except asyncio.CancelledError:
            for pending_task in running_tasks:
                pending_task.cancel()
            if running_tasks:
                await asyncio.gather(*running_tasks, return_exceptions=True)
            raise

    async def run(self, file_mode: FileMode, movie_list: list[Path] | None) -> None:
        try:
            await self._run(file_mode, movie_list)
        finally:
            await self.crawler_provider.close()

    async def _run(self, file_mode: FileMode, movie_list: list[Path] | None) -> None:
        Flags.reset()
        if movie_list is None:
            movie_list = []
        Flags.scrape_start_time = time.time()  # 开始刮削时间
        Flags.file_mode = file_mode  # 刮削模式（工具单文件或主界面/日志点开始正常刮削）

        signal.show_scrape_info("🔎 正在刮削中...")

        signal.set_main_info()  # 清空主界面显示信息
        thread_number = manager.config.thread_number  # 线程数量
        thread_time = manager.config.thread_time  # 线程延时
        signal.label_result.emit(f" 刮削中：{0} 成功：{Flags.succ_count} 失败：{Flags.fail_count}")
        signal.logs_failed_settext.emit("\n\n\n")

        # 日志页面显示开始时间
        Flags.start_time = time.time()
        if file_mode == FileMode.Single:
            signal.show_log_text("🍯 🍯 🍯 NOTE: 当前是单文件刮削模式！")
        elif file_mode == FileMode.Again:
            signal.show_log_text(f"🍯 🍯 🍯 NOTE: 开始重新刮削！！！ 刮削文件数量（{len(movie_list)})")
            n = 0
            for each_f, each_i in Flags.new_again_dic.items():
                n += 1
                if each_i[0]:
                    signal.show_log_text(f"{n} 🖥 File path: {each_f}\n 🚘 File number: {each_i[0]}")
                else:
                    signal.show_log_text(f"{n} 🖥 File path: {each_f}\n 🌐 File url: {each_i[1]}")

        # 获取设置的媒体目录、失败目录、成功目录
        path_settings = get_movie_path_setting()
        movie_path = path_settings.movie_path
        ignore_dirs = path_settings.ignore_dirs
        softlink_path = path_settings.softlink_path

        # 获取待刮削文件列表的相关信息
        if not movie_list:
            if manager.config.scrape_softlink_path:
                await newtdisk_creat_symlink(
                    Switch.COPY_NETDISK_NFO in manager.config.switch_on, movie_path, softlink_path
                )
                movie_path = softlink_path
            signal.show_log_text("\n ⏰ Start time: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
            movie_list = await get_movie_list(file_mode, movie_path, ignore_dirs)
        else:
            signal.show_log_text("\n ⏰ Start time: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        Flags.remain_list = movie_list.copy()
        Flags.can_save_remain = True

        task_count = len(movie_list)
        Flags.total_count = task_count

        if task_count:
            Flags.count_claw += 1
            if manager.config.main_mode == 4:
                signal.show_log_text(f" 🕷 当前为读取模式，并发数（{thread_number}），线程延时（0）秒...")
            else:
                if task_count < thread_number:
                    thread_number = task_count
                signal.show_log_text(f" 🕷 开启异步并发，并发数（{thread_number}），线程延时（{thread_time}）秒...")
            if Switch.REST_SCRAPE in manager.config.switch_on and manager.config.main_mode != 4:
                signal.show_log_text(
                    f'<font color="brown"> 🍯 间歇刮削 已启用，连续刮削 {manager.config.rest_count} 个文件后，将自动休息 {Flags.rest_time_convert} 秒...</font>'
                )

            if task_count > thread_number * 1000:
                signal.show_log_text(f" ⚠ 待刮削任务较多（{task_count}），已启用渐进式任务调度以降低内存峰值。")

            Flags.next_start_time = time.time()

            # 异步并发（按并发数渐进投喂任务，避免大列表一次性创建海量协程）
            await self._run_tasks_with_limit(movie_list, task_count, thread_number)
            signal.label_result.emit(f" 刮削中：0 成功：{Flags.succ_count} 失败：{Flags.fail_count}")
            await save_success_list()  # 保存成功列表
            if signal.stop or Flags.stop_requested:
                return

        signal.show_log_text("================================================================================")
        await _clean_empty_fodlers(movie_path, file_mode)
        end_time = time.time()
        used_time = str(round((end_time - Flags.start_time), 2))
        average_time = str(round((end_time - Flags.start_time) / task_count, 2)) if task_count else used_time
        signal.exec_set_processbar.emit(0)
        signal.set_label_file_path.emit(f"🎉 恭喜！全部刮削完成！共 {task_count} 个文件！用时 {used_time} 秒")
        signal.show_traceback_log(
            f"🎉 All finished!!! Total {task_count} , Success {Flags.succ_count} , Failed {Flags.fail_count} "
        )
        signal.show_log_text(
            f" 🎉🎉🎉 All finished!!! Total {task_count} , Success {Flags.succ_count} , Failed {Flags.fail_count} "
        )
        signal.show_log_text("================================================================================")
        if Flags.failed_list:
            signal.show_log_text("    *** Failed results ****")
            for i in range(len(Flags.failed_list)):
                fail_path, fail_reson = Flags.failed_list[i]
                signal.show_log_text(f" 🔴 {i + 1} {fail_path}\n    {fail_reson}")
                signal.show_log_text("================================================================================")
        signal.show_log_text(
            " ⏰ Start time".ljust(15) + ": " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(Flags.start_time))
        )
        signal.show_log_text(
            " 🏁 End time".ljust(15) + ": " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))
        )
        signal.show_log_text(" ⏱ Used time".ljust(15) + f": {used_time}S")
        signal.show_log_text(" 📺 Movies num".ljust(15) + f": {task_count}")
        signal.show_log_text(" 🍕 Per time".ljust(15) + f": {average_time}S")
        signal.show_log_text("================================================================================")
        signal.show_scrape_info(f"🎉 刮削完成 {task_count}/{task_count}")

        # auto run after scrape
        if EmbyAction.ACTOR_PHOTO_AUTO in manager.config.emby_on:
            await update_emby_actor_photo()
        if manager.config.actor_photo_kodi_auto:
            await creat_kodi_actors(True)

        signal.reset_buttons_status.emit()
        if len(Flags.again_dic):
            Flags.new_again_dic = Flags.again_dic.copy()
            new_movie_list = list(Flags.new_again_dic.keys())
            Flags.again_dic.clear()
            start_new_scrape(FileMode.Again, new_movie_list)
        if Switch.AUTO_EXIT in manager.config.switch_on:
            signal.show_log_text("\n\n 🍔 已启用「刮削后自动退出软件」！")
            count = 5
            for i in range(count):
                signal.show_log_text(f" {count - i} 秒后将自动退出！")
                await asyncio.sleep(1)
            await self.crawler_provider.close()
            signal.exec_exit_app.emit()

    async def process_one_file(self, task: tuple[Path, int, int]) -> None:
        # 获取顺序
        file_path, count, count_all = task
        Flags.counting_order += 1
        count = Flags.counting_order

        # 名字缩写
        show_name = file_path.name
        if len(show_name) > 40:
            show_name = show_name[:40] + "..."

        # 处理间歇任务
        while (
            manager.config.main_mode != 4
            and Switch.REST_SCRAPE in manager.config.switch_on
            and count - Flags.rest_now_begin_count > manager.config.rest_count
        ):
            self._check_stop(show_name)
            await asyncio.sleep(1)

        # 非第一个加延时
        Flags.scrape_starting += 1
        count = Flags.scrape_starting
        thread_time = manager.config.thread_time
        if count == 1 or thread_time == 0 or manager.config.main_mode == 4:
            Flags.next_start_time = time.time()
            signal.show_log_text(f" 🕷 {get_current_time()} 开始刮削：{Flags.scrape_starting}/{count_all} {show_name}")
            thread_time = 0
        else:
            Flags.next_start_time += thread_time

        # 计算本线程开始剩余时间, 休眠并定时检查是否手动停止
        remain_time = int(Flags.next_start_time - time.time())
        if remain_time > 0:
            signal.show_log_text(
                f" ⏱ {get_current_time()}（{remain_time}）秒后开始刮削：{count}/{count_all} {show_name}"
            )
            for i in range(remain_time):
                self._check_stop(show_name)
                await asyncio.sleep(1)

        Flags.scrape_started += 1
        if count > 1 and thread_time != 0:
            signal.show_log_text(f" 🕷 {get_current_time()} 开始刮削：{Flags.scrape_started}/{count_all} {show_name}")

        start_time = time.time()
        file_mode = Flags.file_mode

        # 获取文件基础信息
        file_info = await get_file_info_v2(file_path)
        number = file_info.number
        origin_number = number
        folder_old_path = file_info.folder_path
        file_show_name = file_info.file_show_name
        file_show_path = file_info.file_show_path

        # 显示刮削信息
        progress_value = Flags.scrape_started / count_all * 100
        progress_percentage = f"{progress_value:.2f}%"
        signal.exec_set_processbar.emit(int(progress_value))
        signal.set_label_file_path.emit(
            f"正在刮削： {Flags.scrape_started}/{count_all} {progress_percentage} \n {file_show_path}"
        )
        signal.label_result.emit(
            f" 刮削中：{Flags.scrape_started - Flags.succ_count - Flags.fail_count} 成功：{Flags.succ_count} 失败：{Flags.fail_count}"
        )
        LogBuffer.log().write("\n" + "👆" * 50)
        LogBuffer.log().write("\n 🙈 [file] " + str(file_info.file_path))
        LogBuffer.log().write("\n 🚘 [number] " + number)

        # 如果指定了单一网站，进行提示
        website_single = manager.config.website_single
        if manager.config.scrape_like == "single" and file_mode != FileMode.Single and manager.config.main_mode != 4:
            LogBuffer.log().write(
                f"\n 😸 [Note] You specified 「 {website_single} 」, some videos may not have results! "
            )

        # 获取刮削数据
        json_data = None
        other = None
        try:
            json_data, other = await self._process_one_file(file_info, file_mode)
            if json_data and other:
                if manager.config.main_mode == 4:
                    number = json_data.number  # 读取模式且存在nfo时，可能会导致movie_number改变，需要更新
                Flags.json_data_dic.update({number: ScrapeResult(file_info, json_data, other)})
                for status_number in (origin_number, number):
                    if status_number in Flags.json_get_status and Flags.json_get_status[status_number] is None:
                        Flags.json_get_status[status_number] = True
            elif origin_number in Flags.json_get_status and Flags.json_get_status[origin_number] is None:
                Flags.json_get_status[origin_number] = False
        except Exception as e:
            if origin_number in Flags.json_get_status and Flags.json_get_status[origin_number] is None:
                Flags.json_get_status[origin_number] = False
            self._check_stop(show_name)
            signal.show_traceback_log(traceback.format_exc())
            signal.show_log_text(traceback.format_exc())
            LogBuffer.error().write("scrape file error: " + str(e))
            LogBuffer.log().write("\n" + traceback.format_exc())

        # 显示刮削数据
        try:
            show_data = ShowData.empty()
            show_data.file_info = file_info
            if json_data and other:
                show_data.data = json_data
                show_data.other = other
                Flags.succ_count += 1
                show_data.show_name = (
                    str(Flags.count_claw)
                    + "-"
                    + str(Flags.succ_count)
                    + "."
                    + file_show_name.replace(number, file_info.number)
                    + ("-" if file_info.definition else "")
                    + file_info.definition
                )
                signal.show_list_name("succ", show_data, number)
            else:
                Flags.fail_count += 1
                show_data.show_name = (
                    str(Flags.count_claw)
                    + "-"
                    + str(Flags.fail_count)
                    + "."
                    + file_show_name.replace(number, file_info.number)
                    + ("-" if file_info.definition else "")
                    + file_info.definition
                )
                signal.show_list_name("fail", show_data, number)
                if e := LogBuffer.error().get():
                    LogBuffer.log().write(f"\n 🔴 [Failed] Reason: {e}")
                    if "WinError 5" in e:
                        LogBuffer.log().write(
                            "\n 🔴 该问题为权限问题：请尝试以管理员身份运行，同时关闭其他正在运行的Python脚本！"
                        )
                failed_folder = get_movie_path_setting(file_path).failed_folder
                fail_file_path = await move_file_to_failed_folder(failed_folder, file_path, folder_old_path)
                Flags.failed_list.append((fail_file_path, LogBuffer.error().get()))
                await self._failed_file_info_show(str(Flags.fail_count), fail_file_path, LogBuffer.error().get())
                signal.view_failed_list_settext.emit(f"失败 {Flags.fail_count}")
        except Exception as e:
            self._check_stop(show_name)
            signal.show_traceback_log(traceback.format_exc())
            signal.show_log_text(traceback.format_exc())
            signal.show_log_text(str(e))

        # 显示刮削结果
        try:
            Flags.scrape_done += 1
            count = Flags.scrape_done
            progress_value = count / count_all * 100
            progress_percentage = f"{progress_value:.2f}%"
            used_time = get_used_time(start_time)
            scrape_info_begin = f"{count:d}/{count_all:d} ({progress_percentage}) round({Flags.count_claw}) {split_path(file_path)[1]}    新的刮削线程"
            scrape_info_begin = "\n\n\n" + "👇" * 50 + "\n" + scrape_info_begin
            scrape_info_after = f"\n 🕷 {get_current_time()} {count}/{count_all} {split_path(file_path)[1]} 刮削完成！用时 {used_time} 秒！"
            if manager.config.show_web_log:
                signal.show_log_text(scrape_info_begin + LogBuffer.log().get() + scrape_info_after)
            else:
                fail_reason = LogBuffer.error().get()
                if fail_reason:
                    signal.show_log_text(
                        scrape_info_begin + f"\n 🔴 [Failed] Reason: {fail_reason}" + scrape_info_after
                    )
                else:
                    signal.show_log_text(scrape_info_begin + scrape_info_after)
            remain_count = Flags.scrape_started - count
            if Flags.scrape_started == count_all:
                signal.show_log_text(f" 🕷 剩余正在刮削的线程：{remain_count}")
            signal.label_result.emit(f" 刮削中：{remain_count} 成功：{Flags.succ_count} 失败：{Flags.fail_count}")
            signal.show_scrape_info(f"🔎 已刮削 {count}/{count_all}")
        except Exception as e:
            self._check_stop(show_name)
            signal.show_traceback_log(traceback.format_exc())
            signal.show_log_text(traceback.format_exc())
            signal.show_log_text(str(e))

        # 更新剩余任务
        try:
            try:
                Flags.remain_list.remove(file_path)
                Flags.can_save_remain = True
            except Exception as e1:
                signal.show_log_text(f"remove:  {file_path}\n {str(e1)}\n {traceback.format_exc()}")
        except Exception as e:
            self._check_stop(show_name)
            signal.show_traceback_log(traceback.format_exc())
            signal.show_log_text(traceback.format_exc())
            signal.show_log_text(str(e))

        # 处理间歇刮削
        try:
            if manager.config.main_mode != 4 and Switch.REST_SCRAPE in manager.config.switch_on:
                time_note = f" 🏖 已累计刮削 {count}/{count_all}，已连续刮削 {count - Flags.rest_now_begin_count}/{manager.config.rest_count}..."
                signal.show_log_text(time_note)
                if count - Flags.rest_now_begin_count >= manager.config.rest_count:
                    if Flags.scrape_starting > count:
                        time_note = f" 🏖 当前还存在 {Flags.scrape_starting - count} 个已经在刮削的任务，等待这些任务结束将进入休息状态...\n"
                        signal.show_log_text(time_note)
                        await Flags.sleep_end.wait()  # 等待休眠结束
                    elif Flags.sleep_end.is_set() and count < count_all:
                        Flags.sleep_end.clear()  # 开始休眠
                        Flags.rest_next_begin_time = time.time()  # 下一轮倒计时开始时间
                        time_note = f'\n ⏸ 休息 {Flags.rest_time_convert} 秒，将在 <font color="red">{get_real_time(Flags.rest_next_begin_time + Flags.rest_time_convert)}</font> 继续刮削剩余的 {count_all - count} 个任务...\n'
                        signal.show_log_text(time_note)
                        while (
                            Switch.REST_SCRAPE in manager.config.switch_on
                            and time.time() - Flags.rest_next_begin_time < Flags.rest_time_convert
                        ):
                            if Flags.scrape_starting > count:  # 如果突然调大了文件数量，这时跳出休眠
                                break
                            await asyncio.sleep(1)
                        Flags.rest_now_begin_count = count
                        Flags.sleep_end.set()  # 休眠结束，下一轮开始
                        Flags.next_start_time = time.time() - manager.config.thread_time
                    else:
                        await Flags.sleep_end.wait()
        except Exception as e:
            self._check_stop(show_name)
            signal.show_traceback_log(traceback.format_exc())
            signal.show_log_text(traceback.format_exc())
            signal.show_log_text(str(e))

        LogBuffer.clear_thread()

    async def _process_one_file(
        self, file_info: FileInfo, file_mode: FileMode
    ) -> tuple[CrawlersResult | None, OtherInfo | None]:
        # 处理单个文件刮削
        # 初始化所需变量
        start_time = time.time()
        read_mode = manager.config.read_mode
        file_escape_size = float(manager.config.file_size)
        file_path = file_info.file_path

        # 获取文件信息
        movie_number = file_info.number
        folder_old_path = file_info.folder_path
        file_name = file_info.file_name
        file_ex = file_info.file_ex
        sub_list = file_info.sub_list

        # 获取设置的媒体目录、失败目录、成功目录
        paths = get_movie_path_setting(file_path)
        success_folder = paths.success_folder
        movie_path = paths.movie_path

        # 检查文件大小
        result = await check_file(file_path, file_escape_size)
        if not result:
            # res.outline = split_path(file_path)[1]
            # res.tag = file_path
            return None, None

        is_nfo_existed = False
        res = CrawlersResult.empty()  # todo 保证所有路径上均有 res 值
        # 读取模式
        file_can_download = True
        if manager.config.main_mode == 4:
            nfo_data, info = await get_nfo_data(file_path, movie_number)
            if nfo_data:  # 有nfo
                is_nfo_existed = True
                res = nfo_data
                movie_number = nfo_data.number
                if "has_nfo_update" not in read_mode:  # 不更新并返回
                    show_result(res, start_time)
                    show_movie_info(file_info, nfo_data)
                    LogBuffer.log().write(f"\n 🙉 [Movie] {file_path}")
                    await save_success_list(file_path, file_path)  # 保存成功列表
                    return nfo_data, info

                # 读取模式要不要下载图片等文件
                if "read_download_again" not in read_mode:
                    file_can_download = False
            else:
                if "no_nfo_scrape" not in read_mode:  # 无 nfo 且未勾选 「无nfo时，刮削并执行更新模式」
                    return None, None

        # 判断是否write_nfo
        update_nfo = True
        # 不写nfo的情况：
        if manager.config.main_mode == 2 and Switch.SORT_DEL in manager.config.switch_on:
            # 2模式勾选“删除本地已下载的nfo文件”（暂无效，会直接return）
            update_nfo = False
        elif manager.config.main_mode in [1, 2, 3] or (
            manager.config.main_mode == 4 and not is_nfo_existed and ReadMode.NO_NFO_SCRAPE in read_mode
        ):
            # 1、2、3模式，或4模式启用了“本地之前刮削失败和没有nfo的文件重新刮削”（变量命名有点问题，存在"no_nfo_scrape"意思其实是要刮削）
            # 且
            if DownloadableFile.NFO not in manager.config.download_files:
                # [下载]处不勾选下载nfo时
                update_nfo = False
            if DownloadableFile.NFO in manager.config.keep_files and is_nfo_existed:
                # [下载]处勾选保留nfo且nfo存在时
                update_nfo = False
        elif manager.config.main_mode == 4:
            # 4（读取）模式默认不写nfo
            update_nfo = False
            # 除非
            if is_nfo_existed and ReadMode.HAS_NFO_UPDATE in read_mode and ReadMode.READ_UPDATE_NFO in read_mode:
                # 启用"允许(使用本地 nfo)更新 nfo 文件"时
                update_nfo = True

        # 刮削json_data
        # 获取已刮削的json_data
        enable_shared_json = "." not in movie_number and file_info.mosaic not in ["国产"]
        if enable_shared_json:
            if movie_number not in Flags.json_get_status:
                # 第一次遇到该番号，标记为“正在刮削”
                Flags.json_get_set.add(movie_number)
                Flags.json_get_status[movie_number] = None
                LogBuffer.log().write(f"\n 🟡 [Same Number] 首次刮削，开始共享番号数据：{movie_number}")
            else:
                # 同番号任务等待首个任务完成；若首个任务失败，直接结束等待，避免线程卡死
                LogBuffer.log().write(f"\n 🟡 [Same Number] 等待同番号任务完成：{movie_number}")
                while Flags.json_get_status.get(movie_number) is None:
                    await asyncio.sleep(1)
                if Flags.json_get_status.get(movie_number) is False:
                    LogBuffer.error().write(f"同番号任务失败，取消等待：{movie_number}")
                    return None, None

        pre_data = Flags.json_data_dic.get(movie_number)
        # 已存在该番号数据时直接使用该数据
        if pre_data and enable_shared_json:
            pre_res = pre_data.data
            res = update(pre_res, file_info)

            tags = pre_res.tag.split(",")
            tags = [
                tag
                for tag in tags
                if tag
                not in (  # 移除与具体文件相关的 tag; 分辨率相关 tag 在 add_definition_tag 中会移除; codec tag 无法穷举, 移除常见类型
                    # todo 所有文件相关的 tag 推迟到 write_nfo 时从 file_info 生成, json_data_dic 只存储通用的 tag
                    # "中文字幕",
                    # "无码流出",
                    # "無碼流出",
                    # "无码破解",
                    # "無碼破解",
                    # "无码",
                    # "無碼",
                    # "有码",
                    # "有碼",
                    "国产",
                    "國產",
                    "里番",
                    "裏番",
                    "动漫",
                    "動漫",
                    "H264",
                    "HEVC",
                    "MPEG4",
                    "VP8",
                    "VP9",
                )
            ]
            tags.append(file_info.mosaic)
            if file_info.has_sub:
                tags.append("中文字幕")
            res.tag = ",".join(tags)

        elif not is_nfo_existed:
            # ========================= call crawlers =========================
            # res = await crawl(file_info.crawl_task(), file_mode)

            scraper = FileScraper(manager.config, self.crawler_provider)
            res = await scraper.run(file_info.crawl_task(), file_mode)
            if res is None:
                return None, None
            # 处理 FileInfo 和 CrawlersResult 的共同字段, 即 number/mosaic/letters
            # todo 理想情况, crawl 后应该以 res 为准, 后续不应再访问 file_info 的相关字段
            # todo 注意, 实际上目前各 crawler 返回的 mosaic 和 number 字段并未被使用
            # 1. number 在 crawl 中被更新, 当前只可能取 file_info.number/short_number/appoint_number
            # 2. letters 在 crawl 过程不会变化, 直接取 file_info 的值
            res.letters = file_info.letters
            # 3. res.mosaic 在 crawl 中被更新, 实际上完全是由 file_info 的某些字段决定的, 和初始化 file_info.mosaic 的逻辑存在重复
            file_info.mosaic = res.mosaic

        # 显示json_data结果或日志
        show_result(res, start_time)

        # 映射或翻译
        # 当不存在已刮削数据，或者读取模式允许更新nfo时才进行映射翻译
        if not pre_data and update_nfo:
            deal_some_field(res)  # 处理字段
            replace_special_word(res)  # 替换特殊字符
            await translate_title_outline(res, file_info.cd_part, movie_number)  # 翻译json_data（标题/介绍）
            deal_some_field(res)  # 再处理一遍字段，翻译后可能出现要去除的内容
            await translate_actor(res)  # 映射输出演员名/信息
            translate_info(res, file_info.has_sub)  # 映射输出标签等信息
            replace_word(res)

        # 更新视频分辨率
        definition, codec = await get_video_size(file_path, file_info.number)
        file_info.definition, file_info.codec = definition, codec
        add_definition_tag(res, definition, codec)

        # 显示json_data内容
        show_movie_info(file_info, res)

        # 生成输出文件夹和输出文件的路径
        (
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
        ) = get_output_name(file_info, res, success_folder, file_ex)

        # 判断输出文件的路径是否重复
        if manager.config.soft_link == 0:
            done_file_new_path_list = Flags.file_new_path_dic.get(file_new_path)
            if not done_file_new_path_list:  # 如果字典中不存在同名的情况，存入列表，继续刮削
                Flags.file_new_path_dic[file_new_path] = [file_path]
            else:
                done_file_new_path_list.append(file_path)  # 已存在时，添加到列表，停止刮削
                done_file_new_path_list.sort(reverse=True)
                LogBuffer.error().write(
                    "存在重复文件（指刮削后的文件路径相同！），请检查:\n    🍁 "
                    + "\n    🍁 ".join(str(path) for path in done_file_new_path_list)
                )
                res.outline = split_path(str(file_path))[1]
                res.tag = str(file_path)
                return None, None

        # 判断输出文件夹和文件是否已存在，如无则创建输出文件夹
        other = OtherInfo.empty()
        if not await creat_folder(
            other,
            res,
            folder_new_path,
            file_path,
            file_new_path,
            thumb_new_path_with_filename,
            poster_new_path_with_filename,
        ):
            return None, None

        # 初始化图片已下载地址的字典
        if not Flags.file_done_dic.get(res.number):
            Flags.file_done_dic[res.number] = FileDoneDict(
                poster=None,
                thumb=None,
                fanart=None,
                trailer=None,
                local_poster=None,
                local_thumb=None,
                local_fanart=None,
                local_trailer=None,
            )

        # 视频模式（原来叫整理模式）
        # 视频模式（仅根据刮削数据把电影命名为番号并分类到对应目录名称的文件夹下）
        if manager.config.main_mode == 2:
            # 移动文件
            if await move_movie(other, file_info, file_path, file_new_path):
                if Switch.SORT_DEL in manager.config.switch_on:
                    await deal_old_files(
                        res.number,
                        other,
                        folder_old_path,
                        folder_new_path,
                        file_path,
                        # file_new_path,
                        thumb_new_path_with_filename,
                        poster_new_path_with_filename,
                        fanart_new_path_with_filename,
                        nfo_new_path,
                        # file_ex,
                        poster_final_path,
                        thumb_final_path,
                        fanart_final_path,
                    )  # 清理旧的thumb、poster、fanart、nfo
                await save_success_list(file_path, file_new_path)  # 保存成功列表
                return res, other
            else:
                # 返回MDCx1_1main, 继续处理下一个文件
                return None, None

        # 清理旧的thumb、poster、fanart、extrafanart、nfo
        pic_final_catched, single_folder_catched = await deal_old_files(
            res.number,
            other,
            folder_old_path,
            folder_new_path,
            file_path,
            # file_new_path,
            thumb_new_path_with_filename,
            poster_new_path_with_filename,
            fanart_new_path_with_filename,
            nfo_new_path,
            # file_ex,
            poster_final_path,
            thumb_final_path,
            fanart_final_path,
        )

        # 如果 final_pic_path 没处理过，这时才需要下载和加水印
        if pic_final_catched and file_can_download:
            # 下载thumb
            if not await thumb_download(res, other, file_info.cd_part, folder_new_path, thumb_final_path):
                return None, None

            # 下载艺术图
            await fanart_download(res.number, other, file_info.cd_part, fanart_final_path)

            # 下载poster
            if not await poster_download(res, other, file_info.cd_part, folder_new_path, poster_final_path):
                return None, None

            # 清理冗余图片
            await pic_some_deal(res.number, thumb_final_path, fanart_final_path)

            # 加水印
            await add_mark(other, file_info, res.mosaic)

            # 下载剧照和剧照副本
            if single_folder_catched:
                await extrafanart_download(res.extrafanart, res.extrafanart_from, folder_new_path)
                await extrafanart_copy2(folder_new_path)
                await extrafanart_extras_copy(folder_new_path)

            # 下载trailer、复制主题视频
            # 因为 trailer也有带文件名，不带文件名两种情况，不能使用pic_final_catched。比如图片不带文件名，trailer带文件名这种场景需要支持每个分集去下载trailer
            await trailer_download(res, folder_new_path, folder_old_path, naming_rule)
            await copy_trailer_to_theme_videos(folder_new_path, naming_rule)

        # 生成nfo文件
        await write_nfo(file_info, res, nfo_new_path, folder_new_path, update_nfo)

        # 移动字幕、种子、bif、trailer、其他文件
        if file_info.has_sub:
            await move_sub(folder_old_path, folder_new_path, file_name, sub_list, naming_rule)
        await move_torrent(folder_old_path, folder_new_path, file_name, movie_number, naming_rule)
        await move_bif(folder_old_path, folder_new_path, file_name, naming_rule)
        # self.move_trailer_video(folder_old_path, folder_new_path, file_name, naming_rule)
        await move_other_file(res.number, folder_old_path, folder_new_path, file_name, naming_rule)

        # 移动文件
        if not await move_movie(other, file_info, file_path, file_new_path):
            return None, None
        await save_success_list(file_path, file_new_path)  # 保存成功列表

        # 创建软链接及复制文件
        if manager.config.auto_link:
            if manager.config.success_file_move:
                # 此时 folder_new_path 在 success_folder 目录下
                target_dir = Path(manager.config.localdisk_path) / folder_new_path.relative_to(
                    success_folder, walk_up=True
                )
            else:
                # 此时 folder_new_path == folder_old_path 且在 movie_path 目录下
                target_dir = Path(manager.config.localdisk_path) / folder_old_path.relative_to(movie_path, walk_up=True)
            copy = Switch.COPY_NETDISK_NFO in manager.config.switch_on
            await newtdisk_creat_symlink(copy, folder_new_path, target_dir)

        # json添加封面缩略图路径
        other.poster_path = poster_final_path
        other.thumb_path = thumb_final_path
        other.fanart_path = fanart_final_path
        if not await aiofiles.os.path.exists(thumb_final_path) and await aiofiles.os.path.exists(fanart_final_path):
            other.thumb_path = fanart_final_path

        return res, other

    def _check_stop(self, show_name: str) -> None:
        if signal.stop or Flags.stop_requested:
            Flags.now_kill += 1
            signal.show_log_text(
                f" 🕷 {get_current_time()} 已停止刮削：{Flags.now_kill}/{Flags.total_kills} {show_name}"
            )
            signal.set_label_file_path.emit(
                f"⛔️ 正在停止刮削...\n   正在停止已在运行的任务线程（{Flags.now_kill}/{Flags.total_kills}）..."
            )
            raise StopScrape("手动停止刮削")

    async def _failed_file_info_show(self, count: str, p: Path, error_info: str) -> None:
        info_str = f"{'🔴 ' + count + '.':<3} {p} \n    所在目录: {p.parent} \n    失败原因: {error_info} \n"
        if await aiofiles.os.path.islink(p):
            info_str = f"{'🔴 ' + count + '.':<3} {p} \n    指向文件: {p.resolve()} \n    失败原因: {error_info} \n"
        signal.logs_failed_show.emit(info_str)


def start_new_scrape(file_mode: FileMode, movie_list: list[Path] | None = None) -> None:
    Flags.stop_requested = False
    signal.stop = False
    signal.change_buttons_status.emit()
    signal.exec_set_processbar.emit(0)
    try:
        Flags.start_time = time.time()
        crawler_provider = CrawlerProvider(manager.config, manager.computed.async_client)
        scraper = Scraper(crawler_provider)
        executor.submit(scraper.run(file_mode, movie_list))
    except Exception:
        signal.show_traceback_log(traceback.format_exc())
        signal.show_log_text(traceback.format_exc())


def get_remain_list() -> bool:
    """This function is intended to be sync."""
    remain_list_path = resources.u("remain.txt")
    if not remain_list_path.is_file():
        return False
    with open(remain_list_path, encoding="utf-8", errors="ignore") as f:
        remains = [p for path in f if (line := path.strip()) and (p := Path(line)).suffix]
    Flags.remain_list = remains
    if not len(Flags.remain_list) or Switch.REMAIN_TASK not in manager.config.switch_on:
        return False
    box = QMessageBox(QMessageBox.Icon.Information, "继续刮削", "上次刮削未完成，是否继续刮削剩余任务？")
    box.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
    )
    box.button(QMessageBox.StandardButton.Yes).setText("继续刮削剩余任务")
    box.button(QMessageBox.StandardButton.No).setText("从头刮削")
    box.button(QMessageBox.StandardButton.Cancel).setText("取消")
    box.setDefaultButton(QMessageBox.StandardButton.No)
    reply = box.exec()
    if reply == QMessageBox.StandardButton.Yes:
        signal.show_log_text("🍯 🍯 🍯 NOTE: 用户选择继续刮削剩余任务。")
    elif reply == QMessageBox.StandardButton.No:
        signal.show_log_text("🍯 🍯 🍯 NOTE: 用户选择从头刮削。")
        return False  # 从头刮削
    else:
        signal.show_log_text("🍯 🍯 🍯 NOTE: 已取消本次刮削启动。")
        return True  # 不刮削（包括点取消、ESC、右上角关闭）

    movie_path = manager.config.media_path
    if movie_path == "":
        movie_path = manager.data_folder
    movie_path = Path(movie_path)

    p = Flags.remain_list[0]
    if not is_descendant(p, movie_path):
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            "提醒",
            f"很重要！！请注意：\n当前待刮削目录：{movie_path}\n剩余任务文件路径：{p.resolve()}\n"
            "文件不在当前待刮削目录中, 可能是使用其他配置扫描的！\n"
            "请确认成功输出目录和失败目录是否正确！如果配置不正确，继续刮削可能会导致文件被移动到新配置的输出位置！\n是否继续刮削？",
        )
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("继续")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply == QMessageBox.StandardButton.No:
            return True
    signal.show_log_text(f"🍯 🍯 🍯 NOTE: 继续刮削未完成任务！！！ 剩余未刮削文件数量（{len(Flags.remain_list)})")
    start_new_scrape(FileMode.Default, Flags.remain_list)
    return True


def again_search() -> None:
    Flags.new_again_dic = Flags.again_dic.copy()
    new_movie_list = list(Flags.new_again_dic.keys())
    Flags.again_dic.clear()
    start_new_scrape(FileMode.Again, new_movie_list)


async def move_sub(
    folder_old_path: Path,
    folder_new_path: Path,
    file_name: str,
    sub_list: list[str],
    naming_rule: str,
) -> None:
    copy_flag = False

    # 更新模式 或 读取模式
    if manager.config.main_mode > 2:
        if manager.config.update_mode == "c" and not manager.config.success_file_rename:
            return

    # 软硬链接开时，复制字幕（EMBY 显示字幕）
    elif manager.config.soft_link > 0:
        copy_flag = True

    # 成功移动关、成功重命名关时，返回
    elif not manager.config.success_file_move and not manager.config.success_file_rename:
        return

    for sub in sub_list:
        sub_old_path = str(folder_old_path / (file_name + sub))
        sub_new_path = str(folder_new_path / (naming_rule + sub))
        sub_new_path_chs = str(folder_new_path / (naming_rule + ".chs" + sub))
        if manager.config.subtitle_add_chs and ".chs" not in sub:
            sub_new_path = sub_new_path_chs
        if await aiofiles.os.path.exists(sub_old_path) and not await aiofiles.os.path.exists(sub_new_path):
            if copy_flag:
                if not await copy_file_async(sub_old_path, sub_new_path):
                    LogBuffer.log().write("\n 🔴 Sub copy failed!")
                    return
            elif not await move_file_async(sub_old_path, sub_new_path):
                LogBuffer.log().write("\n 🔴 Sub move failed!")
                return
        LogBuffer.log().write("\n 🍀 Sub done!")
