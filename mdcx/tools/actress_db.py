import datetime
import re
import sqlite3
import traceback
from pathlib import Path

from ..config.manager import manager
from ..models.emby import EMbyActressInfo
from ..signals import signal


class ActressDB:
    DB = None

    @classmethod
    def init_db(cls):
        try:
            #  https://ricardoanderegg.com/posts/python-sqlite-thread-safety/
            cls.DB = sqlite3.connect(Path(manager.config.info_database_path), check_same_thread=False)
            info_count = cls.DB.execute("select count(*) from Info").fetchone()  # 必须实际执行查询才能判断是否连接成功
            signal.show_log_text(f" ✅ 数据库连接成功, 共有 {info_count[0]} 条女优信息")
        except Exception:
            signal.show_traceback_log(traceback.format_exc())
            signal.show_log_text(" ❌ 数据库连接失败, 请检查数据库设置")
            cls.DB = None

    @classmethod
    def update_actor_info_from_db(cls, actor_info: EMbyActressInfo) -> tuple[int, str]:
        if cls.DB is None:
            return 0, "❌ 数据库连接失败, 请检查数据库设置"

        keyword = actor_info.name
        cur = cls.DB.cursor()
        if s := cur.execute(f"select Name, Alias from Names where Alias='{keyword}'").fetchone():
            name, alias = s
        else:
            s = cur.execute(f"select Name, Alias from Names where Alias like '{keyword}%'").fetchone()
            if not s:
                return 0, f"🔴 数据库中未找到姓名: {keyword}"
            name, alias = s

        res = cur.execute(
            f"select Href,Cup,Height,Bust,Waist,Hip,Birthday,Birthplace,Account,CareerPeriod from Info where Name = '{name}'"
        )
        href, cup, height, bust, waist, hip, birthday, birthplace, account, career_period = res.fetchone()
        cur.close()

        # 收集处理结果信息
        messages = []
        messages.append(f"✅ 数据库命中: {alias}")

        # 添加标签
        tags = []
        if cup:
            tags.append("罩杯: " + cup)
        if height:
            tags.append(f"身高: {height}")
        if bust or waist or hip:
            tags.append(f"三围: {bust}/{waist}/{hip}")
        if birthday:
            actor_info.birthday = birthday[:10]
            actor_info.year = birthday[:4]
            tags.append("出生日期: " + birthday[:10])
            tags.append("年龄: " + str(datetime.datetime.now().year - int(birthday[:4])))
        if career_period:
            tags.append("生涯: " + career_period.replace("年", "").replace(" ", "").replace("-", "~"))

        if tags:
            messages.append(f"\t🏷️ 标签已添加: {' | '.join(tags)}")
            actor_info.tags.extend(tags)

        # 添加外部链接
        if "Twitter" not in actor_info.provider_ids and account:
            res = re.search(r"twitter.com/(.*)", account)
            if res:
                actor_info.provider_ids["Twitter"] = res.group(1)
                messages.append(f"\t🐦 Twitter ID 已添加: {res.group(1)}")
        actor_info.provider_ids["minnano-av"] = href
        actor_info.provider_ids["javdb"] = name  # 偷懒, 用名字代替, 对应插件中定义为搜索页
        messages.append(f"\t🌐 minnano-av 链接已添加: {href}")

        # 添加其他信息
        if actor_info.locations == ["日本"] or not actor_info.locations:
            birthplace = "日本" if not birthplace else "日本·" + birthplace.replace("県", "县")
            actor_info.locations = [birthplace]
        if not actor_info.taglines:
            actor_info.taglines = ["日本AV女优"]
        if not actor_info.overview:
            actor_info.overview = "无维基百科信息, 从 minnano-av 数据库补全女优信息"

        return 1, "\n".join(messages)
