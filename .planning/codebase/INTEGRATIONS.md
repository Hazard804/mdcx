# External Integrations

> Last mapped: 2026-04-26

## Scraping Targets (Crawler Sites)

MDCx integrates with **35+ websites** via dedicated crawlers in `mdcx/crawlers/`. Each crawler extracts metadata (title, actors, tags, images, etc.) from a specific site.

### New-Style Crawlers (GenericBaseCrawler)

These use the `parsel` selector and the structured `GenericBaseCrawler[T]` base class in `mdcx/crawlers/base/base.py`:

| Crawler Class    | Site Enum        | Module                         |
|------------------|------------------|--------------------------------|
| `DmmCrawler`     | `Website.DMM`    | `mdcx/crawlers/dmm_new/`      |
| `JavdbCrawler`   | `Website.JAVDB`  | `mdcx/crawlers/javdb_new.py`   |
| `AvbaseCrawler`  | `Website.AVBASE` | `mdcx/crawlers/avbase_new.py`  |
| `MissavCrawler`  | `Website.MISSAV` | `mdcx/crawlers/missav.py`      |

### Legacy Crawlers (v1 function-based)

~31 crawlers registered via `CRAWLER_FUNCS` in `mdcx/crawlers/__init__.py`. Each is a `main()` function wrapped by the compat layer in `mdcx/crawlers/base/compat.py`.

## HTTP Client Stack

| Component     | Usage                                  | File                        |
|---------------|----------------------------------------|-----------------------------|
| `curl_cffi`   | Primary HTTP with browser fingerprint  | `mdcx/web_async.py`        |
| `httpx`       | URL parsing, query params, LLM client  | `mdcx/web_async.py`, `mdcx/llm.py` |
| `aiolimiter`  | Per-host rate limiting (5 req/s default)| `mdcx/web_async.py`        |

## Cloudflare Bypass Integration

`AsyncWebClient` in `mdcx/web_async.py` implements a multi-strategy Cloudflare bypass:

1. **Mirror mode**: Proxies requests through a configurable bypass server (`cf_bypass_url`)
2. **HTML fallback**: Falls back to `/html` endpoint on the bypass server for GET requests
3. **Cookie caching**: Bypass server caches cookies; forced refresh on challenge hits
4. **Independent proxy**: Optional separate proxy for bypass traffic (`cf_bypass_proxy`)

Configuration via `Config.cf_bypass_url` and `Config.cf_bypass_proxy`.

## LLM / AI Integration

| Provider      | Purpose            | File            |
|---------------|--------------------|-----------------|
| OpenAI API    | Translation (titles, outlines) | `mdcx/llm.py` |

- Uses `openai` SDK with configurable base URL (supports any OpenAI-compatible API)
- Rate-limited via `aiolimiter`
- Chain-of-thought stripping (`<think>...</think>` tags removed from responses)
- Configurable model, temperature, prompts, timeout, retry count

Translation falls back through: Google → Baidu → DeepL → DeepLX → LLM (configurable order in `TranslateConfig`).

## Media Server Integration

| Server     | Purpose                          | Files                                |
|------------|----------------------------------|--------------------------------------|
| Emby       | Actor photos, metadata sync      | `mdcx/tools/emby_actor_image.py`, `mdcx/tools/emby_actor_info.py` |
| Jellyfin   | Actor photos, metadata sync      | Same files (unified API)             |

- REST API interaction via `Config.emby_url` + `Config.api_key`
- Features: actor photo update (from gfriends/local), actor info translation, Kodi actor creation

## Image Sources

| Source        | Purpose                    |
|---------------|----------------------------|
| Amazon        | High-definition cover art  |
| Google Images | HD poster/thumb search     |
| gfriends      | Actor photo database       |
| Graphis       | Actor backdrop/face photos |

Image processing pipeline: download → crop → watermark → save. Handled in `mdcx/core/web.py` and `mdcx/core/image.py`.

## Web API (FastAPI Server)

| Endpoint Group | Path Prefix    | File                              |
|----------------|----------------|-----------------------------------|
| Config API     | `/api/v1/`     | `mdcx/server/api/v1/config.py`    |
| Files API      | `/api/v1/`     | `mdcx/server/api/v1/files.py`     |
| Legacy API     | `/api/v1/`     | `mdcx/server/api/v1/legacy.py`    |
| WebSocket      | `/api/v1/ws`   | `mdcx/server/api/v1/ws.py`        |

- API key authentication via header (`mdcx/server/dependencies.py`)
- WebSocket with bearer token auth (`mdcx/server/ws/auth.py`)
- CORS: allow all origins (development setting)
- Static files: serves `ui/dist/` at root

## WebSocket Communication

| Message Type   | Direction       | Purpose                    |
|----------------|-----------------|----------------------------|
| `QT_SINGAL`    | Server → Client | Qt signal forwarding       |
| `PROGRESS`     | Server → Client | Scrape progress updates    |

Managed by `WebSocketManager` in `mdcx/server/ws/manager.py`.

## OpenAPI Client Generation

The web UI uses `@hey-api/openapi-ts` to auto-generate TypeScript API client code:
- Config: `ui/openapi-ts.config.ts`
- Generated files: `ui/src/client/` (schemas, types, SDK, TanStack Query hooks)

## External Data Files

| Resource                    | Purpose                         | Location                       |
|-----------------------------|---------------------------------|--------------------------------|
| Number definitions          | Video ID pattern matching       | `resources/c_number/`          |
| Mapping tables              | Actor name/tag translation maps | `resources/mapping_table/`     |
| Chinese conversion tables   | zhconv overrides                | `resources/zhconv/`            |
| Default config              | Template configuration          | `resources/config/`            |
| Fonts                       | Watermark rendering             | `resources/fonts/`             |
| Icons/Images                | Application assets              | `resources/Img/`               |

## Bundled Native Libraries

| File                    | Purpose                    | Location |
|-------------------------|----------------------------|----------|
| `libcrypto-1_1-x64.dll` | OpenSSL crypto (Windows)  | `libs/`  |
| `libssl-1_1-x64.dll`    | OpenSSL SSL (Windows)     | `libs/`  |
