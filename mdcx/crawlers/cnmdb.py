#!/usr/bin/env python3
import re
import time
from urllib.parse import unquote

from lxml import etree

from ..config.manager import manager
from ..models.log_buffer import LogBuffer
from .guochan import get_number_list


def get_actor_photo(actor):
    actor = actor.split(",")
    data = {}
    for i in actor:
        actor_photo = {i: ""}
        data.update(actor_photo)
    return data


def get_detail_info(html, real_url):
    number = unquote(real_url.split("/")[-1])
    item_list = html.xpath('//ol[@class="breadcrumb"]//text()')
    new_item_list = []
    [new_item_list.append(i) for i in item_list if i.strip()]
    if new_item_list:
        title = new_item_list[-1].strip()
        studio = "麻豆" if "麻豆" in new_item_list[1] else new_item_list[-2].strip()
        title, number, actor, series = get_actor_title(title, number, studio)
        if "系列" in new_item_list[-2]:
            series = new_item_list[-2].strip()
        cover = html.xpath('//div[@class="post-image-inner"]/img/@src')
        cover = cover[0] if cover else ""
        return True, number, title, actor, real_url, cover, studio, series
    return False, "", "", "", "", "", "", ""


def get_search_info(html, number_list):
    item_list = html.xpath('//div[@class="post-item"]')
    for each in item_list:
        title = each.xpath("h3/a/text()")
        if title:
            for n in number_list:
                if n.upper() in title[0].upper():
                    number = n
                    real_url = each.xpath("h3/a/@href")
                    real_url = real_url[0] if real_url else ""
                    cover = each.xpath('div[@class="post-item-image"]/a/div/img/@src')
                    cover = cover[0] if cover else ""
                    studio_url = each.xpath("a/@href")
                    studio_url = studio_url[0] if studio_url else ""
                    studio = each.xpath("a/span/text()")
                    studio = studio[0] if studio else ""
                    if "麻豆" in studio_url:
                        studio = "麻豆"
                    title, number, actor, series = get_actor_title(title[0], number, studio)
                    return True, number, title, actor, real_url, cover, studio, series
    return False, "", "", "", "", "", "", ""


def get_actor_title(title, number, studio):
    temp_list = re.split(r"[\., ]", title.replace("/", "."))
    actor_list = []
    new_title = ""
    series = ""
    for i in range(len(temp_list)):
        if number.upper() in temp_list[i].upper():
            number = temp_list[i]
            continue
        if "系列" in temp_list[i]:
            series = temp_list[i]
            continue
        if i < 2 and ("传媒" in temp_list[i] or studio in temp_list[i]):
            continue
        if i > 2 and (
            studio == temp_list[i] or "麻豆" in temp_list[i] or "出品" in temp_list[i] or "传媒" in temp_list[i]
        ):
            break
        if i < 3 and len(temp_list[i]) <= 4 and len(actor_list) < 1:
            actor_list.append(temp_list[i])
            continue
        if len(temp_list[i]) <= 3 and len(temp_list[i]) > 1:
            actor_list.append(temp_list[i])
            continue
        new_title += "." + temp_list[i]
    title = new_title if new_title else title
    return title.strip("."), number, ",".join(actor_list), series


async def main(
    number,
    appoint_url="",
    file_path="",
    appoint_number="",
    **kwargs,
):
    start_time = time.time()
    website_name = "cnmdb"
    LogBuffer.req().write(f"-> {website_name}")
    title = ""
    cover_url = ""
    web_info = "\n       "
    LogBuffer.info().write(" \n    🌐 cnmdb")
    debug_info = ""
    real_url = appoint_url
    series = ""

    try:
        if real_url:
            debug_info = f"番号地址: {real_url} "
            LogBuffer.info().write(web_info + debug_info)
            response, error = await manager.computed.async_client.get_text(real_url)
            if response is not None:
                detail_page = etree.fromstring(response, etree.HTMLParser())
                result, number, title, actor, real_url, cover_url, studio, series = get_detail_info(
                    detail_page, real_url
                )
            else:
                debug_info = "没有找到数据"
                LogBuffer.info().write(web_info + debug_info)
                raise Exception(debug_info)

        else:
            # 处理番号
            number_list, filename_list = get_number_list(number, appoint_number, file_path)
            for each in number_list:
                real_url = "https://cnmdb.net/" + each
                debug_info = f"请求地址: {real_url} "
                LogBuffer.info().write(web_info + debug_info)
                response, error = await manager.computed.async_client.get_text(real_url)
                if response is not None:
                    detail_page = etree.fromstring(response, etree.HTMLParser())
                    result, number, title, actor, real_url, cover_url, studio, series = get_detail_info(
                        detail_page, real_url
                    )
                    break
            else:
                filename_list = re.split(r"[\.,，]", file_path)
                for each in filename_list:
                    if len(each) < 5 or "传媒" in each or "麻豆" in each:
                        continue
                    search_url = f"https://cnmdb.net/s0?q={each}"
                    debug_info = f"请求地址: {search_url} "
                    LogBuffer.info().write(web_info + debug_info)
                    response, error = await manager.computed.async_client.get_text(search_url)
                    if response is None:
                        debug_info = f"网络请求错误: {error}"
                        LogBuffer.info().write(web_info + debug_info)
                        raise Exception(debug_info)
                    search_page = etree.fromstring(response, etree.HTMLParser())
                    result, number, title, actor, real_url, cover_url, studio, series = get_search_info(
                        search_page, number_list
                    )
                    if result:
                        break
                else:
                    debug_info = "没有匹配的搜索结果"
                    LogBuffer.info().write(web_info + debug_info)
                    raise Exception(debug_info)

        actor_photo = get_actor_photo(actor)

        try:
            dic = {
                "number": number,
                "title": title,
                "originaltitle": title,
                "actor": actor,
                "outline": "",
                "originalplot": "",
                "tag": "",
                "release": "",
                "year": "",
                "runtime": "",
                "score": "",
                "series": series,
                "country": "CN",
                "director": "",
                "studio": studio,
                "publisher": studio,
                "source": "cnmdb",
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
    # print(main('GDCM-018'))
    # print(main('国产一姐裸替演员沈樵Qualla作品.七旬老农的女鬼诱惑.国语原创爱片新高度', file_path='国产一姐裸替演员沈樵Qualla作品.七旬老农的女鬼诱惑.国语原创爱片新高度'))
    # print(main('RS001', file_path='RS-001.红斯灯影像.REDSTEN.淫白大胜利.上.男女水中竞赛.败方被强制插入高潮连连'))
    # print(main('MD-0269', file_path='MD-0269.梁佳芯.唐芯.换妻性爱淫元宵.正月十五操骚鲍.麻豆传媒映画原创中文原版收藏'))
    # print(main('sh-006', file_path='SH-006.谢冰岚.神屌侠侣.是谁操了我的小龙女.涩会传媒'))
    # print(main('PMC-085', file_path='PMC/PMC-085.雪霏.出差借宿小姨子乱伦姐夫.特别照顾的肉体答谢.蜜桃影像传媒.ts'))
    # print(main('TM-0165', file_path='TM0165.王小妮.妈妈的性奴之路.性感少妇被儿子和同学调教成性奴.天美传媒'))
    # print(main('mini06.全裸家政.只為弟弟的學費打工.被玩弄的淫亂家政小妹.mini傳媒'))
    # print(main('mini06', file_path='mini06.全裸家政.只為弟弟的學費打工.被玩弄的淫亂家政小妹.mini傳媒'))
    # print(main('mini06.全裸家政.只为弟弟的学费打工.被玩弄的淫乱家政小妹.mini传媒', file_path='mini06.全裸家政.只为弟弟的学费打工.被玩弄的淫乱家政小妹.mini传媒'))
    # print(main('XSJ138', file_path='XSJ138.养子的秘密教学EP6.薇安姐内射教学.性视界出品'))
    # print(main('DW-006.AV帝王作品.Roxie出演.地方妈妈的性解放.双穴双屌', file_path='DW-006.AV帝王作品.Roxie出演.地方妈妈的性解放.双穴双屌'))
    # print(main('MDJ001-EP3.陈美惠.淫兽寄宿家庭.我和日本父子淫乱的一天.2021麻豆最强跨国合作', file_path='MDJ001-EP3.陈美惠.淫兽寄宿家庭.我和日本父子淫乱的一天.2021麻豆最强跨国合作'))
    # print(main('MKY-TN-003.周宁.乱伦黑料流出.最喜欢爸爸的鸡巴了.麻豆传媒MKY系列', file_path='MKY-TN-003.周宁.乱伦黑料流出.最喜欢爸爸的鸡巴了.麻豆传媒MKY系列'))
    print(main('XSJ138.养子的秘密教学EP6.薇安姐内射教学.性视界出品',
               file_path='XSJ138.养子的秘密教学EP6.薇安姐内射教学.性视界出品'))  # print(main('MAN麻豆女性向系列.MAN-0011.岚湘庭.当男人恋爱时.我可以带你去流浪.也知道下场不怎么样', file_path='MAN麻豆女性向系列.MAN-0011.岚湘庭.当男人恋爱时.我可以带你去流浪.也知道下场不怎么样'))  # print(main('MDL-0009-2.楚梦舒.苏语棠.致八零年代的我们.年少的性欲和冲动.麻豆传媒映画原创中文收藏版', file_path='MDL-0009-2.楚梦舒.苏语棠.致八零年代的我们.年少的性欲和冲动.麻豆传媒映画原创中文收藏版'))  # print(main('MSD-023', file_path='MSD023.袁子仪.杨柳.可爱女孩非亲妹.渴望已久的(非)近亲性爱.麻豆传媒映画.Model.Seeding系列.mp4'))  # print(main('', file_path='夏日回忆 贰'))  # print(main('MDX-0016'))  # print(main('MDSJ-0004'))  # print(main('RS-020'))  # print(main('PME-018.雪霏.禽兽小叔迷奸大嫂.性感身材任我玩弄.蜜桃影像传媒', file_path='PME-018.雪霏.禽兽小叔迷奸大嫂.性感身材任我玩弄.蜜桃影像传媒'))  # print(main('老公在外出差家里的娇妻被入室小偷强迫性交 - 美酱'))  # print(main('', file_path='夏日回忆 贰 HongKongDoll玩偶姐姐.短篇集.夏日回忆 贰.Summer Memories.Part 2.mp4'))  # print(main('', file_path='HongKongDoll玩偶姐姐.短篇集.夏日回忆 贰.Summer Memories.Part 2.mp4'))  # print(main('', file_path="【HongKongDoll玩偶姐姐.短篇集.情人节特辑.Valentine's Day Special-cd2"))  # print(main('', file_path='PMC-062 唐茜.綠帽丈夫連同新弟怒操出軌老婆.強拍淫蕩老婆被操 唐茜.ts'))  # print(main('', file_path='MKY-HS-004.周寗.催情民宿.偷下春药3P干爆夫妇.麻豆传媒映画'))  # print(main('淫欲游戏王.EP6', appoint_number='淫欲游戏王.EP5', file_path='淫欲游戏王.EP6.情欲射龙门.性爱篇.郭童童.李娜.双英战龙根3P混战.麻豆传媒映画.ts')) # EP不带.才能搜到  # print(main('', file_path='PMS-003.职场冰与火.EP3设局.宁静.苏文文.设局我要女人都臣服在我胯下.蜜桃影像传媒'))  # print(main('', file_path='PMS-001 性爱公寓EP04 仨人.蜜桃影像传媒.ts'))  # print(main('', file_path='PMS-001.性爱公寓EP03.ts'))  # print(main('', file_path='MDX-0236-02.沈娜娜.青梅竹马淫乱3P.麻豆传媒映画x逼哩逼哩blibli.ts'))  # print(main('', file_path='淫欲游戏王.EP6.情欲射龙门.性爱篇.郭童童.李娜.双英战龙根3P混战.麻豆传媒映画.ts'))  # main('', file_path='淫欲游戏王.EP6.情欲射龙门.性爱篇.郭童童.李娜.双英战龙根3P混战.麻豆传媒映画.ts')  # print(main('', file_path='麻豆傳媒映畫原版 兔子先生 我的女友是女優 女友是AV女優是怎樣的體驗-美雪樱'))   # 简体搜不到  # print(main('', file_path='麻豆傳媒映畫原版 兔子先生 拉麵店搭訕超可愛少女下-柚木结爱.TS'))  # '麻豆傳媒映畫原版 兔子先生 拉麵店搭訕超可愛少女下-柚木結愛', '麻豆傳媒映畫原版 兔子先生 拉麵店搭訕超可愛少女下-', ' 兔子先生 拉麵店搭訕超可愛少女下-柚木結愛']  # print(main('', file_path='麻豆傳媒映畫原版 兔子先生 我的女友是女優 女友是AV女優是怎樣的體驗-美雪樱.TS'))  # print(main('', file_path='PMS-001 性爱公寓EP02 女王 蜜桃影像传媒 -莉娜乔安.TS'))  # print(main('91CM-081', file_path='91CM-081.田恬.李琼.继母与女儿.三.爸爸不在家先上妹妹再玩弄母亲.果冻传媒.mp4'))  # print(main('91CM-081', file_path='MDJ-0001.EP3.陈美惠.淫兽寄宿家庭.我和日本父子淫乱的一天.麻豆传媒映画.mp4'))  # print(main('91CM-081', file_path='MDJ0001 EP2  AV 淫兽鬼父 陈美惠  .TS'))  # print(main('91CM-081', file_path='MXJ-0005.EP1.弥生美月.小恶魔高校生.与老师共度的放浪补课.麻豆传媒映画.TS'))  # print(main('91CM-081', file_path='MKY-HS-004.周寗.催情民宿.偷下春药3P干爆夫妇.麻豆传媒映画.TS'))  # print(main('91CM-081', file_path='PH-US-002.色控.音乐老师全裸诱惑.麻豆传媒映画.TS'))  # print(main('91CM-081', file_path='MDX-0236-02.沈娜娜.青梅竹马淫乱3P.麻豆传媒映画x逼哩逼哩blibli.TS'))  # print(main('91CM-081', file_path='MD-0140-2.蜜苏.家有性事EP2.爱在身边.麻豆传媒映画.TS'))  # print(main('91CM-081', file_path='MDUS系列[中文字幕].LAX0025.性感尤物渴望激情猛操.RUCK ME LIKE A SEX DOLL.麻豆传媒映画.TS'))  # print(main('91CM-081', file_path='REAL野性派001-朋友的女友讓我最上火.TS'))  # print(main('91CM-081', file_path='MDS-009.张芸熙.巨乳旗袍诱惑.搔首弄姿色气满点.麻豆传媒映画.TS'))  # print(main('91CM-081', file_path='MDS005 被雇主强上的熟女家政妇 大声呻吟被操到高潮 杜冰若.mp4.TS'))  # print(main('91CM-081', file_path='TT-005.孟若羽.F罩杯性感巨乳DJ.麻豆出品x宫美娱乐.TS'))  # print(main('91CM-081', file_path='台湾第一女优吴梦梦.OL误上痴汉地铁.惨遭多人轮番奸玩.麻豆传媒映画代理出品.TS'))  # print(main('91CM-081', file_path='PsychoPorn色控.找来大奶姐姐帮我乳交.麻豆传媒映画.TS'))  # print(main('91CM-081', file_path='鲍鱼游戏SquirtGame.吸舔碰糖.失败者屈辱凌辱.TS'))  # print(main('91CM-081', file_path='导演系列 外卖员的色情体验 麻豆传媒映画.TS'))  # print(main('91CM-081', file_path='MDS007 骚逼女友在作妖-硬上男友当玩具 叶一涵.TS'))  # print(main('MDM-002')) # 去掉标题最后的发行商  # print(main('MDS-007')) # 数字要四位才能搜索到，即 MDS-0007 MDJ001 EP1 我的女优物语陈美惠.TS  # print(main('MDS-007', file_path='MDJ001 EP1 我的女优物语陈美惠.TS')) # 数字要四位才能搜索到，即 MDJ-0001.EP1  # print(main('91CM-090')) # 带横线才能搜到  # print(main('台湾SWAG chloebabe 剩蛋特辑 干爆小鹿'))   # 带空格才能搜到  # print(main('淫欲游戏王EP2'))  # 不带空格才能搜到  # print(main('台湾SWAG-chloebabe-剩蛋特輯-幹爆小鹿'))  # print(main('MD-0020'))  # print(main('mds009'))  # print(main('mds02209'))  # print(main('女王的SM调教'))  # print(main('91CM202'))  # print(main('91CM-202'))
