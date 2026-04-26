# Architecture

> Last mapped: 2026-04-26

## System Overview

MDCx is a **media metadata scraper** with dual frontends:

1. **Desktop GUI** — PyQt5 application (`main.py`)
2. **Web Server** — FastAPI + React SPA (`server.py` + `ui/`)

Both share the same Python backend: config management, crawler engine, file processing, and media server integration.

## Architectural Pattern

**Layered architecture** with clear separation:

1. **Presentation**: Qt controllers/views OR FastAPI routes + React
2. **Signal Abstraction**: `Signals` (Qt) / `ServerSignals` (WS) — swappable at init
3. **Core**: `Scraper` orchestration, file crawling, translation, NFO generation
4. **Crawler**: Site-specific scrapers behind `CrawlerProvider`
5. **Infrastructure**: `AsyncWebClient` (HTTP), `ConfigManager` (config), file I/O

## Key Abstractions

### Signal System (UI Decoupling)

`mdcx/signals.py` defines Qt signals; `mdcx/server/signals.py` provides a WebSocket-based drop-in replacement. `server.py` calls `set_signal(server_signal)` at init to swap implementations. Core engine only depends on the abstract interface.

### Crawler System (Two-Generation Design)

**New crawlers** (`GenericBaseCrawler[T]` in `mdcx/crawlers/base/base.py`):
- Generic over `Context` type for per-crawler state
- Template method: `_run()` → search → detail → post-process
- Uses `parsel.Selector`; 4 crawlers: DMM, JavDB, Avbase, Missav

**Legacy crawlers** (~31 function-based `main()` functions):
- Wrapped by `LegacyCrawler` compat adapter in `mdcx/crawlers/base/compat.py`
- Uses `beautifulsoup4` / `lxml` directly

**Registry**: `register_crawler()` / `get_crawler_compat()` in `mdcx/crawlers/__init__.py`

### Config System

`MDCx.config` (marker) → points to `config.json` → loaded by `ConfigManager` → validates via `Config` (Pydantic BaseModel, ~980 lines) → `manager.config` (global singleton). Supports V1 `.ini` → V2 `.json` auto-migration. JSON Schema drives the Web UI forms.

### Scrape Pipeline

```
Scraper.run()
├── get_movie_list()            # Discover media files
├── _run_tasks_with_limit()     # Async bounded concurrency
│   └── process_one_file()
│       ├── get_file_info_v2()  # Parse filename → FileInfo
│       ├── FileScraper.run()   # Call crawlers, merge → CrawlersResult
│       ├── translate_*()       # Translation pipeline
│       ├── download images     # thumb/poster/fanart/extrafanart
│       ├── add_mark()          # Watermarks
│       ├── write_nfo()         # Generate NFO XML
│       └── move_movie()        # Move/rename files
└── save_success_list()
```

## Data Flow

```
Media File → FileInfo → CrawlerInput → CrawlerResult (per site)
                                              ↓
                                     CrawlersResult (merged)
                                              ↓
                                     Translation/Mapping
                                              ↓
                                  NFO + Images + File Rename
```

## Entry Points

| Entry Point              | Mode           | Command                             |
|--------------------------|----------------|-------------------------------------|
| `main.py`                | Desktop GUI    | `uv run main.py`                   |
| `server.py`              | Web Server     | `MDCX_DEV=1 fastapi dev server.py` |
| `mdcx/cmd/crawl.py`     | CLI crawler    | `uv run crawl`                      |
| `mdcx/cmd/gen_enums.py` | Code generation| `uv run gen_enums`                  |

## Concurrency Model

- **Async-first**: Core scraper uses `asyncio`
- **Bounded concurrency**: Configurable thread count
- **Rate limiting**: Per-host `AsyncLimiter` (5 req/s default)
- **Same-number dedup**: `Flags.json_get_status` coordinates concurrent crawls of identical IDs
- **Rest/pause**: Configurable intermittent scraping
