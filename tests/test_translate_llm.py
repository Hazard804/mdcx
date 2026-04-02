import pytest

from mdcx.base.translate import TranslateResult
from mdcx.config.enums import Language, Translator
from mdcx.config.models import Config
from mdcx.models.types import CrawlersResult


def test_config_update_migrate_legacy_llm_prompt_in_translate_config():
    data = {
        "translate_config": {
            "llm_prompt": "legacy {content}",
        }
    }

    Config.update(data)

    tc = data["translate_config"]
    assert "llm_prompt" not in tc
    assert tc["llm_prompt_title"] == "legacy {content}"
    assert tc["llm_prompt_outline"] == "legacy {content}"


def test_config_update_migrate_legacy_llm_prompt_top_level():
    data = {
        "llm_prompt": "legacy-top {content}",
    }

    Config.update(data)

    tc = data["translate_config"]
    assert tc["llm_prompt_title"] == "legacy-top {content}"
    assert tc["llm_prompt_outline"] == "legacy-top {content}"


def test_config_update_ignores_legacy_youdao_translator():
    data = {
        "translate_config": {
            "translate_by": ["youdao", "google", "baidu"],
        }
    }

    Config.update(data)

    assert data["translate_config"]["translate_by"] == ["google", "baidu"]


@pytest.mark.asyncio
async def test_llm_translate_uses_separate_prompts(monkeypatch: pytest.MonkeyPatch):
    from mdcx.base import translate as base_translate

    cfg = base_translate.manager.config.translate_config
    monkeypatch.setattr(cfg, "llm_prompt_title", "TITLE::{content}::{lang}")
    monkeypatch.setattr(cfg, "llm_prompt_outline", "OUTLINE::{content}::{lang}")

    async def fake_ask(*, user_prompt: str, **kwargs):
        return user_prompt

    monkeypatch.setattr(base_translate.manager.computed.llm_client, "ask", fake_ask)

    title, outline, error = await base_translate.llm_translate("Hello", "World")

    assert error is None
    assert title == "TITLE::Hello::简体中文"
    assert outline == "OUTLINE::World::简体中文"


@pytest.mark.asyncio
async def test_llm_translate_normalizes_literal_linebreaks(monkeypatch: pytest.MonkeyPatch):
    from mdcx.base import translate as base_translate

    cfg = base_translate.manager.config.translate_config
    monkeypatch.setattr(cfg, "llm_prompt_title", "TITLE::{content}")
    monkeypatch.setattr(cfg, "llm_prompt_outline", "OUTLINE::{content}")

    async def fake_ask(*, user_prompt: str, **kwargs):
        if user_prompt.startswith("TITLE::"):
            return "标题第1行\\n标题第2行\\r\\n标题第3行"
        return "简介第1行\\n简介第2行"

    monkeypatch.setattr(base_translate.manager.computed.llm_client, "ask", fake_ask)

    title, outline, error = await base_translate.llm_translate("Hello", "World")

    assert error is None
    assert title == "标题第1行\n标题第2行\n标题第3行"
    assert outline == "简介第1行\n简介第2行"


@pytest.mark.asyncio
async def test_llm_translate_normalizes_br_tags(monkeypatch: pytest.MonkeyPatch):
    from mdcx.base import translate as base_translate

    cfg = base_translate.manager.config.translate_config
    monkeypatch.setattr(cfg, "llm_prompt_title", "TITLE::{content}")
    monkeypatch.setattr(cfg, "llm_prompt_outline", "OUTLINE::{content}")

    async def fake_ask(*, user_prompt: str, **kwargs):
        if user_prompt.startswith("TITLE::"):
            return "第一行<br>第二行<BR />第三行"
        return "甲行&lt;br&gt;乙行"

    monkeypatch.setattr(base_translate.manager.computed.llm_client, "ask", fake_ask)

    title, outline, error = await base_translate.llm_translate("Hello", "World")

    assert error is None
    assert title == "第一行\n第二行\n第三行"
    assert outline == "甲行\n乙行"


@pytest.mark.asyncio
async def test_translate_title_outline_supports_english(monkeypatch: pytest.MonkeyPatch):
    from mdcx.core import translate as core_translate

    class _FieldCfg:
        def __init__(self, language: Language, translate: bool):
            self.language = language
            self.translate = translate

    class _TranslateCfg:
        def __init__(self):
            self.translate_by = [Translator.LLM]

    class _Cfg:
        def __init__(self):
            self.title_sehua = False
            self.title_sehua_zh = False
            self.title_yesjav = False
            self.translate_config = _TranslateCfg()

        def get_field_config(self, _field):
            return _FieldCfg(Language.ZH_CN, True)

    class _Manager:
        def __init__(self):
            self.config = _Cfg()

    async def fake_translate_with_engine(*args, **kwargs):
        title = args[1]
        outline = args[2]
        return TranslateResult(
            title=f"CN::{title}",
            outline=f"CN::{outline}",
            error=None,
            engine=Translator.LLM,
            translated_title=True,
            translated_outline=True,
        )

    monkeypatch.setattr(core_translate, "manager", _Manager())
    monkeypatch.setattr(core_translate, "translate_with_engine", fake_translate_with_engine)
    monkeypatch.setattr(core_translate, "get_translator_skip_reason", lambda _translator: None)

    data = CrawlersResult.empty()
    data.title = "A western movie title"
    data.outline = "An English overview."

    await core_translate.translate_title_outline(data, cd_part="-CD1", movie_number="ABC-123")

    assert data.title == "CN::A western movie title"
    assert data.outline == "CN::An English overview."


@pytest.mark.asyncio
async def test_translate_title_outline_supports_long_english_outline(monkeypatch: pytest.MonkeyPatch):
    from mdcx.core import translate as core_translate

    class _FieldCfg:
        def __init__(self, language: Language, translate: bool):
            self.language = language
            self.translate = translate

    class _TranslateCfg:
        def __init__(self):
            self.translate_by = [Translator.LLM]

    class _Cfg:
        def __init__(self):
            self.title_sehua = False
            self.title_sehua_zh = False
            self.title_yesjav = False
            self.translate_config = _TranslateCfg()

        def get_field_config(self, _field):
            return _FieldCfg(Language.ZH_CN, True)

    class _Manager:
        def __init__(self):
            self.config = _Cfg()

    async def fake_translate_with_engine(*args, **kwargs):
        title = args[1]
        outline = args[2]
        return TranslateResult(
            title=f"CN::{title}",
            outline=f"CN::{outline}",
            error=None,
            engine=Translator.LLM,
            translated_title=True,
            translated_outline=True,
        )

    monkeypatch.setattr(core_translate, "manager", _Manager())
    monkeypatch.setattr(core_translate, "translate_with_engine", fake_translate_with_engine)
    monkeypatch.setattr(core_translate, "get_translator_skip_reason", lambda _translator: None)

    data = CrawlersResult.empty()
    data.title = "Youngermommy.24.11.09"
    data.outline = (
        "Ricky Spanish is on the phone with his friend when his stepmom, Scarlett Mae tells him "
        "it's time to go shopping."
    )

    await core_translate.translate_title_outline(data, cd_part="-CD1", movie_number="Youngermommy.24.11.09")

    assert data.outline.startswith("CN::Ricky Spanish is on the phone")


def test_get_baidu_target_language():
    from mdcx.base.translate import get_baidu_target_language

    assert get_baidu_target_language(Language.ZH_CN) == "zh"
    assert get_baidu_target_language(Language.ZH_TW) == "zh"
    assert get_baidu_target_language(Language.JP) == "jp"
    assert get_baidu_target_language(Language.EN) == "en"


@pytest.mark.asyncio
async def test_translate_title_outline_skips_unconfigured_baidu_and_falls_back(monkeypatch: pytest.MonkeyPatch):
    from mdcx.core import translate as core_translate

    class _FieldCfg:
        def __init__(self, language: Language, translate: bool):
            self.language = language
            self.translate = translate

    class _TranslateCfg:
        def __init__(self):
            self.translate_by = [Translator.BAIDU, Translator.LLM]
            self.baidu_appid = ""
            self.baidu_key = ""
            self.deepl_key = ""
            self.llm_model = "test-model"
            self.llm_key = "test-key"

    class _Cfg:
        def __init__(self):
            self.title_sehua = False
            self.title_sehua_zh = False
            self.title_yesjav = False
            self.translate_config = _TranslateCfg()

        def get_field_config(self, _field):
            return _FieldCfg(Language.ZH_CN, True)

    class _Manager:
        def __init__(self):
            self.config = _Cfg()

    async def fake_translate_with_engine(*args, **kwargs):
        title = args[1]
        outline = args[2]
        return TranslateResult(
            title=f"CN::{title}",
            outline=f"CN::{outline}",
            error=None,
            engine=Translator.LLM,
            translated_title=True,
            translated_outline=True,
        )

    monkeypatch.setattr(core_translate, "manager", _Manager())
    monkeypatch.setattr(core_translate, "translate_with_engine", fake_translate_with_engine)
    monkeypatch.setattr(core_translate.random, "shuffle", lambda items: None)
    monkeypatch.setattr(
        core_translate,
        "get_translator_skip_reason",
        lambda translator: "APP ID、密钥 未配置" if translator == Translator.BAIDU else None,
    )

    data = CrawlersResult.empty()
    data.title = "A western movie title"
    data.outline = "An English overview."

    await core_translate.translate_title_outline(data, cd_part="-CD1", movie_number="ABC-123")

    assert data.title == "CN::A western movie title"
    assert data.outline == "CN::An English overview."


@pytest.mark.asyncio
async def test_translate_title_outline_skip_does_not_fake_translate_via_zhconv(monkeypatch: pytest.MonkeyPatch):
    from mdcx.core import translate as core_translate

    class _FieldCfg:
        def __init__(self, language: Language, translate: bool):
            self.language = language
            self.translate = translate

    class _TranslateCfg:
        def __init__(self):
            self.translate_by = [Translator.BAIDU]
            self.baidu_appid = ""
            self.baidu_key = ""

    class _Cfg:
        def __init__(self):
            self.title_sehua = False
            self.title_sehua_zh = False
            self.title_yesjav = False
            self.translate_config = _TranslateCfg()

        def get_field_config(self, _field):
            return _FieldCfg(Language.ZH_CN, True)

    class _Manager:
        def __init__(self):
            self.config = _Cfg()

    monkeypatch.setattr(core_translate, "manager", _Manager())
    monkeypatch.setattr(
        core_translate,
        "get_translator_skip_reason",
        lambda translator: "APP ID、密钥 未配置" if translator == Translator.BAIDU else None,
    )

    data = CrawlersResult.empty()
    data.title = "乳首快楽"
    data.outline = "女優の物語"

    await core_translate.translate_title_outline(data, cd_part="", movie_number="ABC-123")

    assert data.title == "乳首快楽"
    assert data.outline == "女優の物語"
