from pathlib import Path

import pytest

from mdcx.config.enums import FixedScrapingType, Website
from mdcx.config.models import FieldConfig
from mdcx.core.file_crawler import (
    FileScraper,
    _deal_res,
    _is_suren_number,
    classify_existing_scrape_result,
    classify_scrape_task,
)
from mdcx.core.translate import AVWIKI_SCRAPING_TYPES, _should_query_avwiki_actor
from mdcx.gen.field_enums import CrawlerResultFields
from mdcx.manual import ManualConfig
from mdcx.models.log_buffer import LogBuffer
from mdcx.models.types import CrawlerDebugInfo, CrawlerInput, CrawlerResponse, CrawlerResult, CrawlersResult, CrawlTask


class _FakeCrawler:
    def __init__(self, data: CrawlerResult | None, error: Exception | None = None):
        self._data = data
        self._error = error

    async def run(self, task_input: CrawlerInput) -> CrawlerResponse:
        return CrawlerResponse(
            debug_info=CrawlerDebugInfo(execution_time=0.01, error=self._error),
            data=self._data,
        )


class _FakeCrawlerProvider:
    def __init__(self, website_data: dict[Website, CrawlerResult | tuple[CrawlerResult | None, Exception | None]]):
        self._website_crawlers = {}
        for site, data in website_data.items():
            if isinstance(data, tuple):
                self._website_crawlers[site] = _FakeCrawler(data[0], data[1])
            else:
                self._website_crawlers[site] = _FakeCrawler(data)

    async def get(self, site: Website):
        return self._website_crawlers[site]


class _RecordingCrawler:
    def __init__(self, site: Website, records: list[tuple[str, str]], should_raise: bool = False):
        self._site = site
        self._records = records
        self._should_raise = should_raise

    async def run(self, task_input: CrawlerInput) -> CrawlerResponse:
        self._records.append((self._site.value, task_input.number))
        if self._should_raise:
            raise RuntimeError("boom")

        data = CrawlerResult.empty()
        data.title = "ok"
        data.source = self._site.value
        data.external_id = f"{self._site.value}:id"
        return CrawlerResponse(
            debug_info=CrawlerDebugInfo(execution_time=0.01),
            data=data,
        )


class _RecordingCrawlerProvider:
    def __init__(self, crawlers: dict[Website, _RecordingCrawler]):
        self._website_crawlers = crawlers

    async def get(self, site: Website):
        return self._website_crawlers[site]


class _FakeConfig:
    def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
        if field in (CrawlerResultFields.RUNTIME, CrawlerResultFields.RELEASE, CrawlerResultFields.YEAR):
            return FieldConfig(site_prority=[Website.AVBASE, Website.JAVDB])
        return FieldConfig(site_prority=[])


class _ClassificationConfig:
    fixed_scraping_type = FixedScrapingType.AUTO
    website_youma = {Website.DMM}
    website_wuma = {Website.JAVBUS}
    website_suren = {Website.MGSTAGE}
    website_fc2 = {Website.FC2}
    website_oumei = {Website.THEPORNDB}
    website_guochan = {Website.MDTV}


def _build_result(site: Website, runtime: str = "", release: str = "", year: str = "") -> CrawlerResult:
    result = CrawlerResult.empty()
    result.source = site.value
    result.external_id = f"{site.value}:id"
    result.runtime = runtime
    result.release = release
    result.year = year
    return result


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", True),
        ("00", True),
        ("0.0", True),
        ("0.00", True),
        ("55", False),
        ("", False),
    ],
)
def test_is_invalid_runtime(value: str, expected: bool):
    assert FileScraper._is_invalid_runtime(value) is expected


def test_deal_res_normalize_iso_release():
    result = CrawlersResult.empty()
    result.release = "2023-07-14T01:00:00Z"

    normalized = _deal_res(result)

    assert normalized.release == "2023-07-14"


@pytest.mark.parametrize(
    ("file_number", "short_number", "expected"),
    [
        ("259LUXU-1488", "LUXU-1488", True),
        ("435MFC-142", "MFC-142", True),
        ("SIRO-5533", "", True),
        ("SSIS-001", "", False),
        ("FC2-123456", "", False),
    ],
)
def test_is_suren_number_matches_current_scrape_branch(file_number: str, short_number: str, expected: bool):
    assert _is_suren_number(file_number, short_number) is expected


@pytest.mark.parametrize(
    ("number", "mosaic", "short_number", "expected_type", "expected_sites"),
    [
        ("259LUXU-1488", "", "LUXU-1488", FixedScrapingType.SUREN, {Website.MGSTAGE}),
        ("SIRO-5533", "", "", FixedScrapingType.SUREN, {Website.MGSTAGE}),
        ("FC2-123456", "", "", FixedScrapingType.FC2, {Website.FC2}),
        ("100225_100", "无码", "", FixedScrapingType.WUMA, {Website.JAVBUS}),
        ("100225_101", "無修正", "", FixedScrapingType.WUMA, {Website.JAVBUS}),
        ("ABF-131", "无码破解", "", FixedScrapingType.YOUMA, {Website.DMM}),
        ("ABF-132", "无码流出", "", FixedScrapingType.YOUMA, {Website.DMM}),
        ("ABF-133", "流出", "", FixedScrapingType.YOUMA, {Website.DMM}),
        ("ABF-134", "無碼破解", "", FixedScrapingType.YOUMA, {Website.DMM}),
        ("ABF-135", "無碼流出", "", FixedScrapingType.YOUMA, {Website.DMM}),
        ("MD-1234", "", "", FixedScrapingType.GUOCHAN, {Website.MDTV}),
        ("DANDY-732", "", "", FixedScrapingType.YOUMA, {Website.DMM}),
        ("SSNI00321", "", "", FixedScrapingType.YOUMA, {Website.DMM}),
    ],
)
def test_classify_scrape_task_keeps_existing_type_branches(
    number: str,
    mosaic: str,
    short_number: str,
    expected_type: FixedScrapingType,
    expected_sites: set[Website],
):
    task = CrawlTask.empty()
    task.number = number
    task.mosaic = mosaic
    task.short_number = short_number

    classification = classify_scrape_task(task, _ClassificationConfig())

    assert classification.scraping_type == expected_type
    assert classification.scraping_type_source == "auto"
    assert classification.sites == expected_sites


@pytest.mark.parametrize(
    ("number", "file_path", "expected_website"),
    [
        ("KIN8-4188", "", Website.KIN8),
        ("MYWIFE-1500", "D:/test/mywife/MYWIFE-1500.mp4", Website.MYWIFE),
    ],
)
def test_classify_scrape_task_marks_youma_specific_crawlers(number: str, file_path: str, expected_website: Website):
    task = CrawlTask.empty()
    task.number = number
    if file_path:
        task.file_path = Path(file_path)

    classification = classify_scrape_task(task, _ClassificationConfig())

    assert classification.scraping_type == FixedScrapingType.YOUMA
    assert classification.website == expected_website


def test_classify_existing_scrape_result_uses_nfo_mosaic_without_substring_wuma_match():
    task = CrawlTask.empty()
    task.number = "ABF-131"

    result = CrawlersResult.empty()
    result.number = "ABF-131"
    result.mosaic = "无码破解"

    classification = classify_existing_scrape_result(task, result, _ClassificationConfig())

    assert classification.scraping_type == FixedScrapingType.YOUMA
    assert result.scraping_type == FixedScrapingType.YOUMA
    assert result.scraping_type_source == "auto"


def test_classify_scrape_task_fixed_type_overrides_auto_detection():
    class FixedSurenConfig(_ClassificationConfig):
        fixed_scraping_type = FixedScrapingType.SUREN

    task = CrawlTask.empty()
    task.number = "DANDY-732"

    classification = classify_scrape_task(task, FixedSurenConfig())

    assert classification.scraping_type == FixedScrapingType.SUREN
    assert classification.scraping_type_source == "fixed"
    assert classification.sites == {Website.MGSTAGE}


def test_avwiki_uses_unified_scraping_types():
    assert AVWIKI_SCRAPING_TYPES == {
        FixedScrapingType.YOUMA,
        FixedScrapingType.SUREN,
        FixedScrapingType.FC2,
    }


@pytest.mark.parametrize(
    ("scraping_type", "actors", "expected"),
    [
        (FixedScrapingType.YOUMA, [], True),
        (FixedScrapingType.YOUMA, ["未知演员"], True),
        (FixedScrapingType.YOUMA, ["葵つかさ"], False),
        (FixedScrapingType.SUREN, ["素人"], True),
        (FixedScrapingType.FC2, ["販売者"], True),
        (FixedScrapingType.WUMA, [], False),
    ],
)
def test_avwiki_youma_only_queries_when_actor_unknown_or_empty(
    scraping_type: FixedScrapingType, actors: list[str], expected: bool
):
    result = CrawlersResult.empty()
    result.scraping_type = scraping_type
    result.actors = actors

    assert _should_query_avwiki_actor(result) is expected


@pytest.mark.asyncio
async def test_call_crawlers_runtime_skip_zero(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ManualConfig, "REDUCED_FIELDS", (CrawlerResultFields.RUNTIME,))

    provider = _FakeCrawlerProvider(
        {
            Website.AVBASE: _build_result(Website.AVBASE, "0"),
            Website.JAVDB: _build_result(Website.JAVDB, "55"),
        }
    )
    scraper = FileScraper(_FakeConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "SCUTE-1354"

    result = await scraper._call_crawlers(task_input, {Website.AVBASE, Website.JAVDB})

    assert result is not None
    assert result.runtime == "55"
    assert result.field_sources[CrawlerResultFields.RUNTIME] == Website.JAVDB.value


@pytest.mark.asyncio
async def test_call_crawlers_release_skip_invalid_and_fill_year(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ManualConfig, "REDUCED_FIELDS", (CrawlerResultFields.RELEASE,))

    provider = _FakeCrawlerProvider(
        {
            Website.AVBASE: _build_result(Website.AVBASE, release="0000-00-00"),
            Website.JAVDB: _build_result(Website.JAVDB, release="2024-1-2"),
        }
    )
    scraper = FileScraper(_FakeConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "SIRO-5533"

    result = await scraper._call_crawlers(task_input, {Website.AVBASE, Website.JAVDB})

    assert result is not None
    assert result.release == "2024-01-02"
    assert result.year == "2024"
    assert result.field_sources[CrawlerResultFields.RELEASE] == Website.JAVDB.value


@pytest.mark.asyncio
async def test_call_crawler_restore_number_for_mgstage():
    records: list[tuple[str, str]] = []
    provider = _RecordingCrawlerProvider(
        {
            Website.DMM: _RecordingCrawler(Website.DMM, records),
            Website.MGSTAGE: _RecordingCrawler(Website.MGSTAGE, records),
        }
    )
    scraper = FileScraper(_FakeConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "200GANA-3327"
    task_input.short_number = "GANA-3327"

    await scraper._call_crawler(task_input, Website.DMM)
    assert task_input.number == "200GANA-3327"

    await scraper._call_crawler(task_input, Website.MGSTAGE)
    assert task_input.number == "200GANA-3327"

    assert records == [
        (Website.DMM.value, "GANA-3327"),
        (Website.MGSTAGE.value, "200GANA-3327"),
    ]


@pytest.mark.asyncio
async def test_call_crawler_restore_number_when_exception():
    records: list[tuple[str, str]] = []
    provider = _RecordingCrawlerProvider(
        {
            Website.DMM: _RecordingCrawler(Website.DMM, records, should_raise=True),
        }
    )
    scraper = FileScraper(_FakeConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "200GANA-3327"
    task_input.short_number = "GANA-3327"

    with pytest.raises(RuntimeError, match="boom"):
        await scraper._call_crawler(task_input, Website.DMM)

    assert task_input.number == "200GANA-3327"
    assert records == [(Website.DMM.value, "GANA-3327")]


@pytest.mark.asyncio
async def test_call_specific_crawler_writes_debug_error_to_log_buffer():
    LogBuffer.error().clear()
    provider = _FakeCrawlerProvider({Website.THEPORNDB: (None, RuntimeError("请添加 API Token 后刮削！"))})
    scraper = FileScraper(_FakeConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "Nurumassage.26.02.23"

    result = await scraper._call_specific_crawler(task_input, Website.THEPORNDB)

    assert result is None
    assert "请添加 API Token 后刮削！" in LogBuffer.error().get()
    LogBuffer.error().clear()
