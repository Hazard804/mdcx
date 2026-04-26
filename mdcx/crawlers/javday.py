#!/usr/bin/env python3
import re
import time

from lxml import etree

from ..config.enums import Website
from ..config.manager import manager
from ..models.log_buffer import LogBuffer
from .guochan import get_actor_list, get_lable_list, get_number_list


def get_actor_photo(actor):
    actor = actor.split(",")
    data = {}
    for i in actor:
        actor_photo = {i: ""}
        data.update(actor_photo)
    return data


def get_title(html):
    result = html.xpath('//*[@id="videoInfo"]/div/h1')
    return result[0].text if result else ""


def get_some_info(html, title, file_path):
    series_list = html.xpath('//*[@id="videoInfo"]/div/div/p[3]/span[2]/a/text()')
    tag_list = html.xpath('//*[@id="videoInfo"]/div/div/p[1]/span[2]/a/text()')
    actor_list = html.xpath('//*[@id="videoInfo"]/div/div/p[1]/span[2]/a/text()')

    # 未找到演员时，看热门演员是否在标题和各种信息里
    series = series_list[0] if series_list else ""
    tag = ",".join(tag_list)
    actor_fake_name = any("未知" in item for item in actor_list)
    actor_list = [] if actor_fake_name else actor_list
    if not actor_list:
        all_info = title + series + tag + file_path
        all_actor = get_actor_list()
        for each in all_actor:
            if each in all_info:
                actor_list.append(each)
    new_actor_list = []
    [new_actor_list.append(i) for i in actor_list if i and i not in new_actor_list]

    # # 去除标签里的演员
    # for each in actor_list:
    #     if each in tag_list:
    #         tag_list.remove(each)
    # new_tag_list = []
    # [new_tag_list.append(i) for i in tag_list if i and i not in new_tag_list]

    return series, ",".join(tag_list), ",".join(new_actor_list)


def get_studio(series, tag, lable_list):
    word_list = [series]
    word_list.extend(tag.split(","))
    for word in word_list:
        if word in lable_list:
            return word
    return ""


# def get_real_url(html, number, javday_url, file_path,):
#     real_url = ''
#     a = re.search(r'(\d*[A-Z]{2,})\s*(\d{3,})', number)
#     real_number = number
#     if a:
#         real_number = a[1] + '-' + a[2]
#     result = html.xpath('//h4[@class="post-title"]')
#     cd = re.findall(r'((AV|EP)\d{1})', file_path.upper())
#     for each in result:
#         title = each.xpath('a/@title')[0].upper()
#         href = each.xpath('a/@href')[0]
#         title_1 = title.replace('.', '').replace('-', '').replace(' ', '')
#         number_1 = number.replace('.', '').replace('-', '').replace(' ', '')
#         if number in title or real_number in title or number_1 in title_1:
#             real_url = javday_url + href
#             if cd:
#                 if cd[0][0] in title_1.upper():
#                     break
#             else:
#                 break
#     return real_url


def get_cover(html, javday_url):
    result = html.xpath("/html/head/meta[8]")
    if result:
        result = result[0].get("content")
        if "http" not in result:
            result = javday_url + result
    return result if result else ""


def get_tag(html):  # 获取演员
    result = html.xpath('//div[@class="category"]/a[contains(@href, "/class/")]/text()')
    return ",".join(result)


def get_real_number_title(
    number,
    title,
    number_list,
    appoint_number,
    appoint_url,
    lable_list,
    tag,
    actor,
    series,
):
    # 指定番号时，使用指定番号
    if appoint_number:
        number = appoint_number
        temp_title = title.replace(number, "")
        if len(temp_title) > 4:
            title = temp_title
    else:
        # 当从文件名没有获取番号时或者指定网址时，尝试从标题里获取番号
        if number not in number_list or appoint_url:
            title_number_list, filename_list = get_number_list(number, appoint_number, title)
            if title_number_list:
                number = title_number_list[0]
                number_list = title_number_list

        # 从文件名或标题中获取到番号时，对番号进行处理：番号里面没有横线时加横线
        if number in number_list:
            if number != title:
                title = title.replace(number, "").replace(number.lower(), "")
            if "-" not in number:
                if re.search(r"[A-Z]{4,}\d{2,}", number):
                    result = re.search(r"([A-Z]{4,})(\d{2,})", number)
                    number = result[1] + "-" + result[2]
                else:
                    result = re.search(r"\d{3,}", number)
                    if result:
                        number = number.replace(result[0], "-" + result[0])
            if number != title:
                title = title.replace(number, "")
        # 否则使用标题作为番号
        else:
            number = title
    temp_title = get_real_title(title, number_list, lable_list, tag, actor, series)
    if number == title:
        number = temp_title

    # 添加分集标识
    cd = re.findall(r"((AV|EP)\d{1})", title.upper())
    if cd and cd[0][0] not in number:
        number = number + " " + cd[0][0]

    return number, temp_title


def get_real_title(
    title,
    number_list,
    lable_list,
    tag,
    actor,
    series,
):
    # 去除标题里的番号
    for number in number_list:
        title = title.replace(number, "")

    # 去除标题后的发行商
    title_list = re.split("[. ]", title)
    if len(title_list) > 1:
        for key in lable_list:
            for each in title_list:
                if key in each:
                    title_list.remove(each)
        if title_list[-1].lower() == "x":
            title_list.pop()
        title = " ".join(title_list)
    for each in tag.split(","):
        if each:
            title = title.replace("" + each, "")
    for each in actor.split(","):
        if each:
            title = title.replace(" " + each, "")
    title = title.lstrip(series + " ").replace("..", ".").replace("  ", " ")

    return title.replace(" x ", "").replace(" X ", "").strip(" -.")


async def main(
    number,
    appoint_url="",
    file_path="",
    appoint_number="",
    **kwargs,
):
    lable_list = get_lable_list()
    start_time = time.time()
    website_name = "javday"
    LogBuffer.req().write(f"-> {website_name}")
    web_info = "\n       "
    LogBuffer.info().write(" \n    🌐 javday")
    debug_info = ""

    javday_url = manager.config.get_site_url(Website.JAVDAY, "https://javday.tv")
    real_url = appoint_url
    real_html_content = ""
    try:
        # 处理番号
        number_list, filename_list = get_number_list(number, appoint_number, file_path)
        if not real_url:
            total_number_list = number_list + filename_list
            number_list_new = list(set(total_number_list))
            number_list_new.sort(key=total_number_list.index)
            for number in number_list_new:
                testNumberUrl = javday_url + f"/videos/{number}/"
                debug_info = f'搜索地址: {testNumberUrl} {{"wd": {number}}}'
                LogBuffer.info().write(web_info + debug_info)
                html_content, error = await manager.computed.async_client.get_text(testNumberUrl)
                if html_content is None:
                    debug_info = f"网络请求错误: {error}"
                    LogBuffer.info().write(web_info + debug_info)
                else:
                    if "你似乎來到了沒有視頻存在的荒原" in html_content:
                        debug_info = f"找不到番号: {number}"
                        LogBuffer.info().write(web_info + debug_info)
                        continue
                    debug_info = f"找到网页: {testNumberUrl}"
                    real_url = testNumberUrl
                    real_html_content = html_content
                    break
            else:
                raise Exception(debug_info)

        if real_url:
            html_info = etree.fromstring(real_html_content, etree.HTMLParser())
            title = get_title(html_info)  # 获取标题
            if not title:
                debug_info = "数据获取失败: 未获取到title！"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)
            series, tag, actor = get_some_info(html_info, title, file_path)
            actor_photo = get_actor_photo(actor)
            cover_url = get_cover(html_info, javday_url)  # 获取cover
            release = ""
            year = ""
            studio = get_studio(series, tag, lable_list)
            number, title = get_real_number_title(
                number, title, number_list, appoint_number, appoint_url, lable_list, tag, actor, series
            )

            try:
                dic = {
                    "number": number,
                    "title": title,
                    "originaltitle": title,
                    "actor": actor,
                    "outline": "",
                    "originalplot": "",
                    "tag": tag,
                    "release": release,
                    "year": year,
                    "runtime": "",
                    "score": "",
                    "series": series,
                    "country": "CN",
                    "director": "",
                    "studio": studio,
                    "publisher": studio,
                    "source": "javday",
                    "website": real_url,
                    "actor_photo": actor_photo,
                    "thumb": cover_url,
                    "poster": "",
                    "extrafanart": [],
                    "trailer": "",
                    "image_download": False,
                    "image_cut": "no",
                    "mosaic": "国产",
                    "wanted": "",
                }
                debug_info = "数据获取成功！"
                LogBuffer.info().write(web_info + debug_info)

            except Exception as e:
                debug_info = f"数据生成出错: {str(e)}"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)

    except Exception as e:
        # print(traceback.format_exc())
        LogBuffer.error().write(str(e))
        dic = {
            "title": "",
            "thumb": "",
            "website": "",
        }
    dic = {website_name: {"zh_cn": dic, "zh_tw": dic, "jp": dic}}
    LogBuffer.req().write(f"({round(time.time() - start_time)}s) ")
    return dic


if __name__ == "__main__":
    # yapf: disable
    # print(main('Md0165-4'))
    # print(main('GDCM-018'))
    # print(main('MKY-JB-010'))
    # print(main('PMC-085', file_path='PMC/PMC-085.雪霏.出差借宿小姨子乱伦姐夫.特别照顾的肉体答谢.蜜桃影像传媒.ts'))
    # print(main('TM-0165', file_path='TM0165.王小妮.妈妈的性奴之路.性感少妇被儿子和同学调教成性奴.天美传媒'))
    # print(main('mini06.全裸家政.只為弟弟的學費打工.被玩弄的淫亂家政小妹.mini傳媒'))
    # print(main('mini06', file_path='mini06.全裸家政.只為弟弟的學費打工.被玩弄的淫亂家政小妹.mini傳媒'))
    # print(main('mini06.全裸家政.只为弟弟的学费打工.被玩弄的淫乱家政小妹.mini传媒'))
    # print(main('', file_path='夏日回忆 贰'))
    # print(main('MDX-0016'))
    # print(main('MDSJ-0004'))
    # print(main('RS-020'))
    # print(main('PME-018.雪霏.禽兽小叔迷奸大嫂.性感身材任我玩弄.蜜桃影像传媒', file_path='PME-018.雪霏.禽兽小叔迷奸大嫂.性感身材任我玩弄.蜜桃影像传媒'))
    # print(main('老公在外出差家里的娇妻被入室小偷强迫性交 - 美酱'))
    # print(main('', file_path='夏日回忆 贰 HongKongDoll玩偶姐姐.短篇集.夏日回忆 贰.Summer Memories.Part 2.mp4'))
    # print(main('', file_path='HongKongDoll玩偶姐姐.短篇集.夏日回忆 贰.Summer Memories.Part 2.mp4'))
    # print(main('', file_path="【HongKongDoll玩偶姐姐.短篇集.情人节特辑.Valentine's Day Special-cd2"))
    # print(main('', file_path='PMC-062 唐茜.綠帽丈夫連同新弟怒操出軌老婆.強拍淫蕩老婆被操 唐茜.ts'))
    # print(main('', file_path='MKY-HS-004.周寗.催情民宿.偷下春药3P干爆夫妇.麻豆传媒映画'))
    # print(main('淫欲游戏王.EP6', appoint_number='淫欲游戏王.EP5', file_path='淫欲游戏王.EP6.情欲射龙门.性爱篇.郭童童.李娜.双英战龙根3P混战.麻豆传媒映画.ts')) # EP不带.才能搜到
    # print(main('', file_path='PMS-003.职场冰与火.EP3设局.宁静.苏文文.设局我要女人都臣服在我胯下.蜜桃影像传媒'))
    # print(main('', file_path='PMS-001 性爱公寓EP04 仨人.蜜桃影像传媒.ts'))
    # print(main('', file_path='PMS-001.性爱公寓EP03.ts'))
    # print(main('', file_path='MDX-0236-02.沈娜娜.青梅竹马淫乱3P.麻豆传媒映画x逼哩逼哩blibli.ts'))
    # print(main('', file_path='淫欲游戏王.EP6.情欲射龙门.性爱篇.郭童童.李娜.双英战龙根3P混战.麻豆传媒映画.ts'))
    # print(main('', file_path='麻豆傳媒映畫原版 兔子先生 我的女友是女優 女友是AV女優是怎樣的體驗-美雪樱'))   # 简体搜不到
    # print(main('', file_path='麻豆傳媒映畫原版 兔子先生 拉麵店搭訕超可愛少女下-柚木结爱.TS'))
    # '麻豆傳媒映畫原版 兔子先生 拉麵店搭訕超可愛少女下-柚木結愛', '麻豆傳媒映畫原版 兔子先生 拉麵店搭訕超可愛少女下-', ' 兔子先生 拉麵店搭訕超可愛少女下-柚木結愛']
    # print(main('', file_path='麻豆傳媒映畫原版 兔子先生 我的女友是女優 女友是AV女優是怎樣的體驗-美雪樱.TS'))
    # print(main('', file_path='PMS-001 性爱公寓EP02 女王 蜜桃影像传媒 -莉娜乔安.TS'))
    # print(main('91CM-081', file_path='91CM-081.田恬.李琼.继母与女儿.三.爸爸不在家先上妹妹再玩弄母亲.果冻传媒.mp4'))
    # print(main('91CM-081', file_path='MDJ-0001.EP3.陈美惠.淫兽寄宿家庭.我和日本父子淫乱的一天.麻豆传媒映画.mp4'))
    # print(main('91CM-081', file_path='MDJ0001 EP2  AV 淫兽鬼父 陈美惠  .TS'))
    # print(main('91CM-081', file_path='MXJ-0005.EP1.弥生美月.小恶魔高校生.与老师共度的放浪补课.麻豆传媒映画.TS'))
    # print(main('91CM-081', file_path='MKY-HS-004.周寗.催情民宿.偷下春药3P干爆夫妇.麻豆传媒映画.TS'))
    # print(main('91CM-081', file_path='PH-US-002.色控.音乐老师全裸诱惑.麻豆传媒映画.TS'))
    # print(main('91CM-081', file_path='MDX-0236-02.沈娜娜.青梅竹马淫乱3P.麻豆传媒映画x逼哩逼哩blibli.TS'))
    # print(main('91CM-081', file_path='MD-0140-2.蜜苏.家有性事EP2.爱在身边.麻豆传媒映画.TS'))
    # print(main('91CM-081', file_path='MDUS系列[中文字幕].LAX0025.性感尤物渴望激情猛操.RUCK ME LIKE A SEX DOLL.麻豆传媒映画.TS'))
    # print(main('91CM-081', file_path='REAL野性派001-朋友的女友讓我最上火.TS'))
    # print(main('91CM-081', file_path='MDS-009.张芸熙.巨乳旗袍诱惑.搔首弄姿色气满点.麻豆传媒映画.TS'))
    # print(main('91CM-081', file_path='MDS005 被雇主强上的熟女家政妇 大声呻吟被操到高潮 杜冰若.mp4.TS'))
    # print(main('91CM-081', file_path='TT-005.孟若羽.F罩杯性感巨乳DJ.麻豆出品x宫美娱乐.TS'))
    # print(main('91CM-081', file_path='台湾第一女优吴梦梦.OL误上痴汉地铁.惨遭多人轮番奸玩.麻豆传媒映画代理出品.TS'))
    # print(main('91CM-081', file_path='PsychoPorn色控.找来大奶姐姐帮我乳交.麻豆传媒映画.TS'))
    # print(main('91CM-081', file_path='鲍鱼游戏SquirtGame.吸舔碰糖.失败者屈辱凌辱.TS'))
    # print(main('91CM-081', file_path='导演系列 外卖员的色情体验 麻豆传媒映画.TS'))  # 标题去除系列
    # print(main('91CM-081', file_path='MDS007 骚逼女友在作妖-硬上男友当玩具 叶一涵.TS'))
    # print(main('', file_path='WTB-075 酒店妹包养软饭男 为了让他振作只好以身相许 乌托邦.ts'))    # 标题里有\t
    # print(main('', file_path='杏吧八戒1 - 3000约操18岁大一新生，苗条身材白嫩紧致.ts'))  # 分词匹配，带标点或者整个标题去匹配
    # print(main('', file_path='萝莉社 女大学生找模特兼职 被要求裸露拍摄 被套路内射.ts'))  # 分词匹配，带标点或者整个标题去匹配
    print(main('',
               file_path='/sp/sp6/国产测试/MD-0240 周處除三嗨.mp4'))  # print(main('MDM-002')) # 去掉标题最后的发行商  # print(main('MDS-0007')) # 数字要四位才能搜索到，即 MDS-0007 MDJ001 EP1 我的女优物语陈美惠.TS  # print(main('MDS-007', file_path='MDJ001 EP1 我的女优物语陈美惠.TS')) # 数字要四位才能搜索到，即 MDJ-0001.EP1  # print(main('91CM-090')) # 带横线才能搜到  # print(main('台湾SWAG chloebabe 剩蛋特辑 干爆小鹿'))   # 带空格才能搜到  # print(main('淫欲游戏王EP2'))  # 不带空格才能搜到  # print(main('台湾SWAG-chloebabe-剩蛋特輯-幹爆小鹿'))  # print(main('MD-0020'))  # print(main('mds009'))  # print(main('女王的SM调教'))  # print(main('91CM202'))  # print(main('必射客 没钱买披萨只好帮外送员解决问题 大象传媒.ts', file_path='必射客 没钱买披萨只好帮外送员解决问题 大象传媒.ts'))  # print(main('', file_path='素人自制舒舒 富婆偷情被偷拍 亏大了！50W买个视频还被操.ts'))  # print(main('', file_path='/sp/sp3/国产/2021年10月份 國產原創原版合集/20211003 91CM-191 你好同学ep5 MSD011/[c0e0.com]实战现场 .TS'))
