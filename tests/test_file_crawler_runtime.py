import pytest

from mdcx.config.enums import Website
from mdcx.config.models import FieldConfig
from mdcx.core.file_crawler import FileScraper
from mdcx.gen.field_enums import CrawlerResultFields
from mdcx.manual import ManualConfig
from mdcx.models.types import CrawlerDebugInfo, CrawlerInput, CrawlerResponse, CrawlerResult


class _FakeCrawler:
    def __init__(self, data: CrawlerResult):
        self._data = data

    async def run(self, task_input: CrawlerInput) -> CrawlerResponse:
        return CrawlerResponse(
            debug_info=CrawlerDebugInfo(execution_time=0.01),
            data=self._data,
        )


class _FakeCrawlerProvider:
    def __init__(self, website_data: dict[Website, CrawlerResult]):
        self._website_crawlers = {site: _FakeCrawler(data) for site, data in website_data.items()}

    async def get(self, site: Website):
        return self._website_crawlers[site]


class _FakeConfig:
    def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
        if field in (CrawlerResultFields.RUNTIME, CrawlerResultFields.RELEASE, CrawlerResultFields.YEAR):
            return FieldConfig(site_prority=[Website.AVBASE, Website.JAVDB])
        return FieldConfig(site_prority=[])


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
