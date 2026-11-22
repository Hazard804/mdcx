import time

import httpx
import pytest
from openai import APIStatusError, APITimeoutError, AuthenticationError

from mdcx.base.translate import TranslateResult
from mdcx.config.enums import Language, Translator
from mdcx.config.models import Config
from mdcx.llm import LLMClient, LLMError, LLMErrorKind, classify_llm_exception
from mdcx.models.types import CrawlersResult

_FAKE_REQUEST = httpx.Request("POST", "https://llm.example.com/v1/chat/completions")


def test_classify_llm_exception_separates_timeout_from_auth():
    timeout_error = classify_llm_exception(APITimeoutError(request=_FAKE_REQUEST), elapsed=61.0)
    auth_error = classify_llm_exception(
        AuthenticationError("bad key", response=httpx.Response(401, request=_FAKE_REQUEST), body=None)
    )

    assert timeout_error.kind is LLMErrorKind.TIMEOUT
    assert timeout_error.retryable is True
    assert "61s" in timeout_error.message()
    assert auth_error.kind is LLMErrorKind.AUTH
    assert auth_error.retryable is False


def test_llm_error_message_marks_partial_output():
    err = LLMError(LLMErrorKind.TIMEOUT, elapsed=90.0, partial_chars=128)

    assert "已接收 128 字" in err.message()
    assert "可调大 LLM 读取超时" in err.message()


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


@pytest.mark.asyncio
async def test_translate_with_engine_reports_llm_timeout_reason(monkeypatch: pytest.MonkeyPatch):
    from mdcx.base import translate as base_translate

    async def fake_ask(**kwargs):
        raise LLMError(LLMErrorKind.TIMEOUT, elapsed=60.0)

    monkeypatch.setattr(base_translate.manager.computed.llm_client, "ask", fake_ask)

    result = await base_translate.translate_with_engine(
        Translator.LLM,
        "title",
        "outline",
        title_language=Language.ZH_CN,
        outline_language=Language.ZH_CN,
    )

    assert result.success is False
    assert result.error is not None
    assert "超时" in result.error
    assert result.outline == "outline"


@pytest.mark.asyncio
async def test_translate_with_engine_keeps_title_when_outline_fails(monkeypatch: pytest.MonkeyPatch):
    from mdcx.base import translate as base_translate

    cfg = base_translate.manager.config.translate_config
    monkeypatch.setattr(cfg, "llm_prompt_title", "TITLE::{content}")
    monkeypatch.setattr(cfg, "llm_prompt_outline", "OUTLINE::{content}")

    async def fake_ask(*, user_prompt: str, **kwargs):
        if user_prompt.startswith("TITLE::"):
            return "中文标题"
        raise LLMError(LLMErrorKind.TIMEOUT, elapsed=60.0)

    monkeypatch.setattr(base_translate.manager.computed.llm_client, "ask", fake_ask)

    result = await base_translate.translate_with_engine(
        Translator.LLM,
        "English title",
        "English outline",
        title_language=Language.ZH_CN,
        outline_language=Language.ZH_CN,
    )

    # 简介失败不应连带丢弃已经翻译好的标题
    assert result.translated_title is True
    assert result.title == "中文标题"
    assert result.translated_outline is False
    assert result.outline == "English outline"
    assert result.success is True
    # 有字段成功时 error 不再表示整体失败, 具体原因保留在字段级错误里
    assert result.error is None
    assert result.outline_error is not None
    assert "超时" in result.outline_error


@pytest.mark.asyncio
async def test_translate_title_outline_keeps_title_when_outline_fails(monkeypatch: pytest.MonkeyPatch):
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
            outline=outline,
            error="LLM 请求超时",
            engine=Translator.LLM,
            translated_title=True,
            translated_outline=False,
            outline_error="LLM 请求超时",
        )

    monkeypatch.setattr(core_translate, "manager", _Manager())
    monkeypatch.setattr(core_translate, "translate_with_engine", fake_translate_with_engine)
    monkeypatch.setattr(core_translate, "get_translator_skip_reason", lambda _translator: None)

    data = CrawlersResult.empty()
    data.title = "A western movie title"
    data.outline = "An English overview."

    await core_translate.translate_title_outline(data, cd_part="-CD1", movie_number="ABC-123")

    assert data.title == "CN::A western movie title"
    assert data.outline == "An English overview."


def test_should_fallback_to_non_stream_only_for_stream_specific_errors():
    # 流式空内容/请求被拒绝/解析失败时, 值得退回普通请求
    assert LLMError(LLMErrorKind.EMPTY, "模型返回内容为空").should_fallback_to_non_stream is True
    assert LLMError(LLMErrorKind.BAD_REQUEST, "bad request").should_fallback_to_non_stream is True
    # 超时与网络错误即使描述里带 stream 字样, 也不应误触发降级
    assert (
        LLMError(LLMErrorKind.TIMEOUT, "Request timed out while reading stream").should_fallback_to_non_stream is False
    )
    assert LLMError(LLMErrorKind.NETWORK, "connection reset").should_fallback_to_non_stream is False
    # 明确说明不支持流式时才降级
    assert LLMError(LLMErrorKind.SERVER, "This model does not support stream").should_fallback_to_non_stream is True


def test_classify_451_as_content_filter():
    err = classify_llm_exception(
        APIStatusError(
            "It appears to contain prohibited or sensitive content",
            response=httpx.Response(451, request=_FAKE_REQUEST),
            body=None,
        )
    )

    # 内容审核拦截重试无效, 也不应退化成普通请求
    assert err.kind is LLMErrorKind.CONTENT_FILTER
    assert err.retryable is False
    assert err.should_fallback_to_non_stream is False
    assert "审核" in err.message()
    assert "451" in err.message()


def test_empty_result_is_retryable():
    # 兼容接口偶发返回空响应, 属于可重试的瞬时问题
    assert LLMError(LLMErrorKind.EMPTY, "模型返回内容为空").retryable is True


def test_empty_error_distinguishes_reasoning_only():
    from mdcx.llm import _clean_and_validate_text

    with pytest.raises(LLMError) as exc_info:
        _clean_and_validate_text("", elapsed=70.0, partial_chars=0, reasoning_chars=3200)

    assert exc_info.value.kind is LLMErrorKind.EMPTY
    assert "思考内容" in exc_info.value.detail


def _make_llm_client() -> LLMClient:
    return LLMClient(
        api_key="test-key",
        base_url="https://llm.example.com/v1",
        timeout=httpx.Timeout(1.0),
        rate=(100, 1),
    )


@pytest.mark.asyncio
async def test_llm_ask_retries_timeout_up_to_max_try(monkeypatch: pytest.MonkeyPatch):
    client = _make_llm_client()
    calls: list[dict] = []

    async def fake_request(**kwargs):
        calls.append(kwargs)
        raise LLMError(LLMErrorKind.TIMEOUT, elapsed=1.0)

    monkeypatch.setattr(client, "_request", fake_request)

    with pytest.raises(LLMError):
        await client.ask(model="test-model", system_prompt="s", user_prompt="u", max_try=3)

    # 超时只放大一次, 但仍应跑满 max_try 次尝试, 不能被压缩成 2 次
    assert len(calls) == 3
    assert calls[0]["timeout"] is None
    assert calls[1]["timeout"].read == 2.0
    assert calls[2]["timeout"].read == 2.0
    await client.close()


@pytest.mark.asyncio
async def test_llm_ask_falls_back_to_non_stream_on_empty(monkeypatch: pytest.MonkeyPatch):
    client = _make_llm_client()
    streams: list[bool] = []

    async def fake_request(**kwargs):
        streams.append(kwargs["stream"])
        if kwargs["stream"]:
            raise LLMError(LLMErrorKind.EMPTY, "模型返回内容为空")
        return "正文"

    monkeypatch.setattr(client, "_request", fake_request)

    text = await client.ask(model="test-model", system_prompt="s", user_prompt="u", max_try=1)

    assert text == "正文"
    assert streams == [True, False]
    assert client._stream_enabled("test-model") is False
    await client.close()


@pytest.mark.asyncio
async def test_stream_fallback_cooldown_recovers():
    client = _make_llm_client()

    client._disable_stream("test-model")
    assert client._stream_enabled("test-model") is False

    # 模拟冷却期结束, 应重新允许尝试流式
    with client._stream_lock:
        client._stream_disabled["test-model"] = time.monotonic() - 1

    assert client._stream_enabled("test-model") is True
    await client.close()


@pytest.mark.asyncio
async def test_llm_ask_disables_thinking_by_default(monkeypatch: pytest.MonkeyPatch):
    client = _make_llm_client()
    calls: list[dict] = []

    async def fake_request(**kwargs):
        calls.append(kwargs)
        return "正文"

    monkeypatch.setattr(client, "_request", fake_request)

    text = await client.ask(model="test-model", system_prompt="s", user_prompt="u", max_try=1)

    assert text == "正文"
    # 默认就应关闭模型思考, 避免推理模型先用几十秒输出 reasoning
    assert calls[0]["extra_body"] == {"enable_thinking": False}
    await client.close()


@pytest.mark.asyncio
async def test_llm_ask_keeps_caller_thinking_switch(monkeypatch: pytest.MonkeyPatch):
    client = _make_llm_client()
    calls: list[dict] = []

    async def fake_request(**kwargs):
        calls.append(kwargs)
        return "正文"

    monkeypatch.setattr(client, "_request", fake_request)

    await client.ask(
        model="test-model",
        system_prompt="s",
        user_prompt="u",
        max_try=1,
        extra_body={"enable_thinking": True, "top_p": 0.9},
    )

    # 调用方显式指定时应以其为准
    assert calls[0]["extra_body"] == {"enable_thinking": True, "top_p": 0.9}
    await client.close()


@pytest.mark.asyncio
async def test_llm_ask_drops_thinking_param_when_server_rejects(monkeypatch: pytest.MonkeyPatch):
    client = _make_llm_client()
    calls: list[dict] = []

    async def fake_request(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise LLMError(LLMErrorKind.BAD_REQUEST, "unknown field enable_thinking", status=400)
        return "正文"

    monkeypatch.setattr(client, "_request", fake_request)

    text = await client.ask(model="test-model", system_prompt="s", user_prompt="u", max_try=1)

    # 去掉参数重试不应消耗尝试次数, 且该模型后续不再携带
    assert text == "正文"
    assert calls[0]["extra_body"] == {"enable_thinking": False}
    assert calls[1]["extra_body"] is None
    assert client._thinking_param_enabled("test-model") is False

    await client.ask(model="test-model", system_prompt="s", user_prompt="u", max_try=1)
    assert calls[2]["extra_body"] is None
    await client.close()


@pytest.mark.asyncio
async def test_llm_ask_retries_empty_result(monkeypatch: pytest.MonkeyPatch):
    client = _make_llm_client()
    # 关掉流式, 直接在非流式路径上验证空结果可重试
    client._disable_stream("test-model")
    calls: list[dict] = []

    async def fake_request(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise LLMError(LLMErrorKind.EMPTY, "模型返回内容为空")
        return "正文"

    monkeypatch.setattr(client, "_request", fake_request)

    text = await client.ask(model="test-model", system_prompt="s", user_prompt="u", max_try=2)

    assert text == "正文"
    assert len(calls) == 2
    await client.close()
