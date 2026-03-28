import asyncio
import hashlib
import random
import re
import time
from typing import Literal, cast
from urllib.parse import quote

from ..config.enums import Language
from ..config.manager import manager
from ..config.models import Translator
from ..signals import signal


async def youdao_translate(title: str, outline: str):
    url = "https://fanyi.youdao.com/translate?smartresult=dict&smartresult=rule"
    msg = f"{title}\n{outline}"
    lts = str(int(time.time() * 1000))
    salt = lts + str(random.randint(0, 10))
    sign = hashlib.md5(("fanyideskweb" + msg + salt + "Ygy_4c=r#e#4EX^NUGUc5").encode("utf-8")).hexdigest()

    data = {
        "i": msg,
        "from": "AUTO",
        "to": "zh-CHS",
        "smartresult": "dict",
        "client": "fanyideskweb",
        "salt": salt,
        "sign": sign,
        "lts": lts,
        "bv": "c6b8c998b2cbaa29bd94afc223bc106c",
        "doctype": "json",
        "version": "2.1",
        "keyfrom": "fanyi.web",
        "ue": "UTF-8",
        "typoResult": "true",
        "action": "FY_BY_CLICKBUTTION",
    }
    headers = {
        "Cookie": random.choice(
            [
                "OUTFOX_SEARCH_USER_ID=833904829@10.169.0.84",
                "OUTFOX_SEARCH_USER_ID=-10218418@11.136.67.24;",
                "OUTFOX_SEARCH_USER_ID=1989505748@10.108.160.19;",
                "OUTFOX_SEARCH_USER_ID=2072418438@218.82.240.196;",
                "OUTFOX_SEARCH_USER_ID=1768574849@220.181.76.83;",
                "OUTFOX_SEARCH_USER_ID=-2153895048@10.168.8.76;",
            ]
        ),
        "Referer": "https://fanyi.youdao.com/?keyfrom=dict2.top",
    }
    res, error = await manager.computed.async_client.post_json(url, data=data, headers=headers)
    if res is None:
        return title, outline, f"请求失败！可能是被封了，可尝试更换代理！错误：{error}"
    else:
        res = cast("dict", res)
        translateResult = res.get("translateResult")
        if not translateResult:
            return title, outline, f"返回数据未找到翻译结果！返回内容：{res}"
        else:
            list_count = len(translateResult)
            if list_count:
                i = 0
                if title:
                    i = 1
                    title_result_list = translateResult[0]
                    title_list = [a.get("tgt") for a in title_result_list]
                    title_temp = "".join(title_list)
                    if title_temp:
                        title = title_temp
                if outline:
                    outline_temp = ""
                    for j in range(i, list_count):
                        outline_result_list = translateResult[j]
                        outline_list = [a.get("tgt") for a in outline_result_list]
                        outline_temp += "".join(outline_list) + "\n"
                    outline_temp = outline_temp.strip("\n")
                    if outline_temp:
                        outline = outline_temp
    return title, outline.strip("\n"), ""


async def _deepl_translate(text: str, source_lang: Literal["JA", "EN"] = "JA") -> str | None:
    """调用 DeepL API 翻译文本"""
    if not text:
        return ""

    deepl_key = manager.config.translate_config.deepl_key.strip()
    if not deepl_key:
        return None

    # 确定 API URL, 免费版本的 key 包含 ":fx" 后缀，付费版本的 key 不包含 ":fx" 后缀
    deepl_url = "https://api-free.deepl.com" if ":fx" in deepl_key else "https://api.deepl.com"
    url = f"{deepl_url}/v2/translate"
    # 构造请求头
    headers = {"Content-Type": "application/json", "Authorization": f"DeepL-Auth-Key {deepl_key}"}
    # 构造请求体
    data = {"text": [text], "source_lang": source_lang, "target_lang": "ZH"}
    res, error = await manager.computed.async_client.post_json(url, json_data=data, headers=headers)
    if res is None:
        signal.add_log(f"DeepL API 请求失败: {error}")
        return None
    if "translations" in res and len(res["translations"]) > 0:
        return res["translations"][0]["text"]
    else:
        signal.add_log(f"DeepL API 返回数据异常: {res}")
        return None


async def deepl_translate(title: str, outline: str, ls: Literal["JA", "EN"] = "JA"):
    """DeepL 翻译接口"""
    r1, r2 = await asyncio.gather(_deepl_translate(title, ls), _deepl_translate(outline, ls))
    if r1 is None or r2 is None:
        return "", "", "DeepL 翻译失败! 查看网络日志以获取更多信息"
    return r1, r2, None


async def _deeplx_translate(text: str, source_lang: Literal["JA", "EN"] = "JA") -> str | None:
    """调用 DeepLX URL 翻译文本"""
    if not text:
        return ""

    deeplx_url = manager.config.translate_config.deeplx_url.strip()
    if not deeplx_url:
        return None

    url = f"{deeplx_url.rstrip('/')}"
    headers = {"Content-Type": "application/json"}
    data = {"text": text, "source_lang": source_lang, "target_lang": "ZH"}

    res, error = await manager.computed.async_client.post_json(url, json_data=data, headers=headers)
    if res is None:
        signal.add_log(f"DeepLX API 请求失败: {error}")
        return None
    if "data" in res:
        return res["data"]  # 直接返回字符串
    else:
        signal.add_log(f"DeepLX API 返回数据异常: {res}")
        return None


async def deeplx_translate(title: str, outline: str, ls: Literal["JA", "EN"] = "JA"):
    """DeepLX 翻译接口"""
    r1, r2 = await asyncio.gather(_deeplx_translate(title, ls), _deeplx_translate(outline, ls))
    if r1 is None or r2 is None:
        return "", "", "DeepLX 翻译失败! 查看网络日志以获取更多信息"
    return r1, r2, None


def _normalize_translated_linebreaks(text: str) -> str:
    text = (
        text.replace("\r\n", "\n").replace("\r", "\n").replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    )
    text = re.sub(r"(?i)&lt;\s*br\s*/?\s*&gt;", "\n", text)
    return re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)


async def _llm_translate(text: str, prompt_template: str, target_language: str = "简体中文") -> str | None:
    """调用 LLM 翻译文本"""
    if not text:
        return ""
    translated = await manager.computed.llm_client.ask(
        model=manager.config.translate_config.llm_model,
        system_prompt="You are a professional translator.",
        user_prompt=prompt_template.replace("{content}", text).replace("{lang}", target_language),
        temperature=manager.config.translate_config.llm_temperature,
        max_try=manager.config.translate_config.llm_max_try,
        log_fn=signal.add_log,
    )
    if translated is None:
        return None
    return _normalize_translated_linebreaks(translated)


async def llm_translate(title: str, outline: str, target_language: str = "简体中文"):
    translate_config = manager.config.translate_config
    r1, r2 = await asyncio.gather(
        _llm_translate(title, translate_config.llm_prompt_title, target_language),
        _llm_translate(outline, translate_config.llm_prompt_outline, target_language),
    )
    if r1 is None or r2 is None:
        return "", "", "LLM 翻译失败! 查看网络日志以获取更多信息"
    return r1, r2, None


async def _google_translate(msg: str) -> tuple[str | None, str]:
    if not msg:
        return "", ""
    msg_unquote = quote(msg)
    url = f"https://translate.google.com/translate_a/single?client=gtx&sl=auto&tl=zh-CN&dt=t&q={msg_unquote}"
    response, error = await manager.computed.async_client.get_json(url)
    if response is None:
        return None, error
    translated = "".join([sen[0] for sen in response[0]])
    translated = translated.replace("＃", "#")
    return translated, ""


async def google_translate(title: str, outline: str) -> tuple[str, str, str | None]:
    (r1, e1), (r2, e2) = await asyncio.gather(_google_translate(title), _google_translate(outline))
    if r1 is None or r2 is None:
        return "", "", f"google 翻译失败! {e1} {e2}"
    return r1, r2, None


def get_translator_skip_reason(translator: Translator) -> str | None:
    translate_config = manager.config.translate_config

    def _missing_reason(fields: list[tuple[str, str]]) -> str | None:
        missing = [name for name, value in fields if not value.strip()]
        if not missing:
            return None
        return f"{'、'.join(missing)} 未配置"

    if translator == Translator.BAIDU:
        return _missing_reason([("APP ID", translate_config.baidu_appid), ("密钥", translate_config.baidu_key)])
    if translator == Translator.DEEPL:
        return _missing_reason([("DeepL API Key", translate_config.deepl_key)])
    if translator == Translator.DEEPLX:
        return _missing_reason([("DeepLX URL", translate_config.deeplx_url)])
    if translator == Translator.LLM:
        return _missing_reason([("LLM Model", translate_config.llm_model), ("LLM API Key", translate_config.llm_key)])
    return None


def get_baidu_target_language(language: Language | str) -> str:
    if language == Language.ZH_CN or language == Language.ZH_CN.value:
        return "zh"
    if language == Language.ZH_TW or language == Language.ZH_TW.value:
        return "zh"
    if language == Language.EN or language == Language.EN.value:
        return "en"
    if language == Language.JP or language == Language.JP.value:
        return "jp"
    return "zh"


async def _baidu_translate_message(msg: str, target_lang: str) -> tuple[list[str] | None, str]:
    if not msg:
        return [], ""

    translate_config = manager.config.translate_config
    salt = str(int(time.time() * 1000)) + str(random.randint(0, 9))
    sign = hashlib.md5(f"{translate_config.baidu_appid}{msg}{salt}{translate_config.baidu_key}".encode()).hexdigest()
    data = {
        "q": msg,
        "from": "auto",
        "to": target_lang,
        "appid": translate_config.baidu_appid,
        "salt": salt,
        "sign": sign,
    }
    response, error = await manager.computed.async_client.post_json(
        "https://fanyi-api.baidu.com/api/trans/vip/translate",
        data=data,
    )
    if response is None:
        return None, f"百度翻译请求失败: {error}"

    response = cast("dict", response)
    if error_code := response.get("error_code"):
        error_msg = response.get("error_msg", "")
        return None, f"百度翻译失败! {error_code} {error_msg}".strip()

    trans_result = response.get("trans_result")
    if not trans_result:
        return None, f"百度翻译返回数据异常: {response}"

    return [str(item.get("dst", "")) for item in trans_result], ""


def _merge_baidu_result(lines: list[str], title: str, outline: str) -> tuple[str, str]:
    title_result = title
    outline_result = outline

    if title:
        title_result = lines[0] if lines else title
        if outline:
            outline_result = "\n".join(lines[1:]).strip("\n")
    elif outline:
        outline_result = "\n".join(lines).strip("\n")

    return title_result, outline_result


async def baidu_translate(
    title: str,
    outline: str,
    title_target_lang: str = "zh",
    outline_target_lang: str = "zh",
) -> tuple[str, str, str | None]:
    if not title and not outline:
        return "", "", None

    if title_target_lang == outline_target_lang:
        msg = f"{title}\n{outline}" if title and outline else title or outline
        lines, error = await _baidu_translate_message(msg, title_target_lang)
        if lines is None:
            return "", "", error
        title_result, outline_result = _merge_baidu_result(lines, title, outline)
        return title_result, outline_result, None

    (title_lines, title_error), (outline_lines, outline_error) = await asyncio.gather(
        _baidu_translate_message(title, title_target_lang),
        _baidu_translate_message(outline, outline_target_lang),
    )
    if title_lines is None or outline_lines is None:
        return "", "", " ".join(filter(None, [title_error, outline_error]))

    title_result = "\n".join(title_lines).strip("\n") if title else ""
    outline_result = "\n".join(outline_lines).strip("\n") if outline else ""
    return title_result, outline_result, None
