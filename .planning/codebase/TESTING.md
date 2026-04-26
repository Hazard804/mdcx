# Testing

> Last mapped: 2026-04-26

## Framework

| Tool             | Purpose                | Config Location     |
|------------------|------------------------|---------------------|
| pytest           | Test runner            | `pyproject.toml`    |
| pytest-asyncio   | Async test support     | `pyproject.toml`    |
| pytest-cov       | Coverage reporting     | `pyproject.toml`    |

**Run command**: `uv run pytest`

## Test Structure

```
tests/
├── __init__.py
├── conftest.py                    # (if any shared fixtures)
├── core/                          # Core logic tests
│   ├── test_name_flags.py         # File naming flag tests
│   └── test_web_amazon.py         # Amazon image search tests (61K)
├── crawlers/                      # Crawler-specific tests
│   ├── conftest.py                # Crawler test fixtures
│   ├── parser.py                  # Parser test utilities (7.8K)
│   ├── test_avbase.py
│   ├── test_compat.py
│   ├── test_crawler.py
│   ├── test_dmm_trailer_url.py    # DMM trailer URL parsing (31K)
│   ├── test_faleno.py
│   ├── test_fc2_trailer.py
│   ├── test_getchu.py
│   ├── test_iqqtv.py
│   ├── test_jav321.py             # JAV321 parsing tests (9.6K)
│   ├── test_javbus.py
│   ├── test_madouqu.py
│   ├── test_missav.py
│   ├── test_mmtv.py
│   └── test_parsers.py
├── test_actor_stop.py             # Actor processing tests
├── test_base_web.py               # Base web utilities tests
├── test_config_conversion.py      # Config v1→v2 migration tests
├── test_config_network.py         # Network config tests
├── test_file_crawler_runtime.py   # FileCrawler runtime tests
├── test_jellyfin_actor_api.py     # Jellyfin/Emby API tests
├── test_link_target_dir_name.py   # Link target naming tests
├── test_nfo_external_id_tag.py    # NFO external ID tests
├── test_nfo_read.py               # NFO reading tests
├── test_nfo_write_escape.py       # NFO XML escaping tests (6.2K)
├── test_number_definition.py      # Number pattern recognition tests
├── test_path.py                   # Path utility tests
├── test_scraper_remain_list.py    # Scraper remain list tests
├── test_scraper_shared_number.py  # Same-number dedup tests
├── test_translate_llm.py          # LLM translation tests (11.5K)
├── test_ui_schema.py              # UI schema generation tests (8.5K)
├── test_utils.py                  # General utility tests
├── test_video.py                  # Video processing tests
├── test_web_amazon_data.py        # Amazon data tests
├── test_web_async_cf_bypass.py    # Cloudflare bypass tests (25K)
├── test_web_async_url_sanitize.py # URL sanitization tests
└── random_generator.py            # Test data generator utility
```

## Test Coverage Areas

| Area                 | Coverage Level | Notable Test Files                     |
|----------------------|----------------|----------------------------------------|
| Cloudflare bypass    | **Extensive**  | `test_web_async_cf_bypass.py` (25K)    |
| Crawlers (parsing)   | **Good**       | 12+ crawler test files                 |
| Config migration     | **Moderate**   | `test_config_conversion.py`            |
| NFO generation       | **Moderate**   | `test_nfo_*.py` (3 files)              |
| Number recognition   | **Moderate**   | `test_number_definition.py`            |
| LLM translation      | **Good**       | `test_translate_llm.py` (11.5K)        |
| URL sanitization     | **Moderate**   | `test_web_async_url_sanitize.py`       |
| UI schema            | **Good**       | `test_ui_schema.py` (8.5K)             |
| Amazon search        | **Extensive**  | `test_web_amazon.py` (61K)             |
| File operations      | **Moderate**   | `test_file_crawler_runtime.py`         |
| Web UI               | **None**       | No frontend tests exist                |
| Integration (E2E)    | **None**       | No end-to-end tests                    |

## Test Patterns

### Crawler Tests

Crawler tests use saved HTML fixtures and verify parsing:
```python
# tests/crawlers/conftest.py provides fixtures
# Tests verify specific parsers extract correct data from HTML snapshots
```

### Async Tests

Uses `pytest-asyncio` for async test functions:
```python
@pytest.mark.asyncio
async def test_something():
    result = await async_function()
    assert result == expected
```

## CI Pipeline

File: `.github/workflows/ci.yaml`

- Triggered on: push/PR to main
- Steps: checkout → uv setup → install deps → pytest
- Platforms: Not multi-platform in CI (local testing covers Windows/Mac/Linux)

## Frontend Testing

**No frontend tests exist.** The `ui/` directory has no test files, no test framework configured, and no test scripts in `package.json`.
