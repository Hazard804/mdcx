from typing import Any

from .enums import DownloadableFile, HDPicSource, Website

CURRENT_CONFIG_VERSION = 2


def _str_to_list(v: str | list[Any] | None, sep: str = ",", unique: bool = True) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        items = [str(item).strip() for item in v]
    else:
        items = [item.strip() for item in v.replace("，", sep).split(sep)]
    items = [item for item in items if item]
    if unique:
        return list(dict.fromkeys(items))
    return items


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _migrate_download_file_option(value: Any) -> Any:
    value = _enum_value(value)
    if value == "youma_use_poster":
        return None
    if value == DownloadableFile.POSTER_AUTO_BEST.value:
        return DownloadableFile.POSTER_AUTO_BEST.value
    return value


def _is_removed_airav_site(site: object) -> bool:
    return site == Website.AIRAV or site == Website.AIRAV.value


def _migrate_site_list(value: Any) -> Any:
    if isinstance(value, str):
        return [site for site in _str_to_list(value, ",") if not _is_removed_airav_site(site)]
    if isinstance(value, list | set):
        return [site for site in value if not _is_removed_airav_site(site)]
    return value


def _migrate_field_config_sites(value: Any) -> None:
    if not isinstance(value, dict):
        return
    sites = value.get("site_prority")
    if isinstance(sites, list):
        value["site_prority"] = [site for site in sites if not _is_removed_airav_site(site)]


def _migrate_removed_hd_pic_sources(data: dict[str, Any]) -> None:
    valid_values = {HDPicSource.AMAZON.value}
    hd_pics = data.get("download_hd_pics")
    if isinstance(hd_pics, str):
        items: list[Any] = _str_to_list(hd_pics, ",")
    elif isinstance(hd_pics, list | set):
        items = list(hd_pics)
    else:
        return
    data["download_hd_pics"] = [item for item in items if str(_enum_value(item)) in valid_values]


def migrate_config_data(data: dict[str, Any]) -> list[str]:
    """
    统一处理配置结构变更.

    所有可恢复的旧配置差异都应在这里归一化，再交给 Pydantic 做强校验。
    """
    warnings: list[str] = []

    data.pop("google_used", None)
    data.pop("google_exclude", None)
    _migrate_removed_hd_pic_sources(data)

    if _is_removed_airav_site(data.get("website_single")):
        data["website_single"] = Website.AIRAV_CC.value
    for key, value in list(data.items()):
        if key.startswith("website_") and key != "website_single":
            data[key] = _migrate_site_list(value)

    if isinstance(field_configs := data.get("field_configs"), dict):
        for value in field_configs.values():
            _migrate_field_config_sites(value)
    if isinstance(type_field_configs := data.get("type_field_configs"), dict):
        for field_configs in type_field_configs.values():
            if not isinstance(field_configs, dict):
                continue
            for value in field_configs.values():
                _migrate_field_config_sites(value)

    if "proxy_type" in data:
        data["use_proxy"] = data["proxy_type"] != "no"
    if isinstance(r := data.get("proxy"), str):
        r = r.strip()
        if all(schema not in r for schema in ["http://", "https://", "socks5://", "socks5h://"]):
            data["proxy"] = "http://" + r
    if isinstance(r := data.get("cf_bypass_url"), str):
        r = r.strip().rstrip("/")
        if r and all(schema not in r for schema in ["http://", "https://"]):
            r = "http://" + r
        data["cf_bypass_url"] = r
    if isinstance(r := data.get("cf_bypass_proxy"), str):
        r = r.strip()
        if r and all(schema not in r for schema in ["http://", "https://", "socks4://", "socks5://", "socks5h://"]):
            r = "http://" + r
        data["cf_bypass_proxy"] = r

    if isinstance(r := data.get("nfo_tag_actor_contains"), str):
        data["nfo_tag_actor_contains"] = _str_to_list(r, "|")
    if isinstance(r := data.get("use_database"), int):
        data["use_database"] = bool(r)
    if isinstance(r := data.get("local_library"), str):
        data["local_library"] = _str_to_list(r, ",")

    if isinstance(download_files := data.get("download_files"), str):
        data["download_files"] = [
            item
            for value in _str_to_list(download_files, ",")
            if (item := _migrate_download_file_option(value)) is not None
        ]
    elif isinstance(download_files, list | set):
        data["download_files"] = [
            item for value in download_files if (item := _migrate_download_file_option(value)) is not None
        ]

    if isinstance(translate_config := data.get("translate_config"), dict):
        old_prompt = translate_config.pop("llm_prompt", None)
        if isinstance(old_prompt, str):
            translate_config.setdefault("llm_prompt_title", old_prompt)
            translate_config.setdefault("llm_prompt_outline", old_prompt)
        if isinstance(translate_by := translate_config.get("translate_by"), list):
            translate_config["translate_by"] = [item for item in translate_by if item != "youdao"]
    if isinstance(old_prompt := data.get("llm_prompt"), str):
        translate_config = data.setdefault("translate_config", {})
        if isinstance(translate_config, dict):
            translate_config.setdefault("llm_prompt_title", old_prompt)
            translate_config.setdefault("llm_prompt_outline", old_prompt)

    data["config_version"] = CURRENT_CONFIG_VERSION
    return warnings
