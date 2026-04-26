# Concerns

> Last mapped: 2026-04-26

## Technical Debt

### 1. Massive Generated/Controller Files

| File                                         | Size    | Issue                              |
|----------------------------------------------|---------|------------------------------------|
| `mdcx/views/MDCx.py`                        | 872 KB  | Auto-generated from `.ui`, unmaintainable |
| `mdcx/controllers/main_window/main_window.py`| 160 KB  | Monolithic controller, >3000 lines |
| `mdcx/controllers/main_window/load_config.py`| 57 KB   | Huge config-to-UI binding          |
| `mdcx/controllers/main_window/save_config.py`| 41 KB   | Huge UI-to-config saving           |
| `mdcx/controllers/main_window/style.py`      | 33 KB   | Inline Qt stylesheet               |

**Impact**: These files are extremely hard to modify, debug, or review. The main window controller in particular is a "God object".

### 2. Two-Generation Crawler System

Only 4 crawlers use the new `GenericBaseCrawler[T]` pattern; ~31 remain as legacy function-based crawlers using beautifulsoup4. The compat layer adds complexity.

**Impact**: Inconsistent error handling, duplicated patterns, harder to add features uniformly.

### 3. Global Mutable State

`mdcx/models/flags.py` uses a `Flags` class with many class-level mutable attributes:
- `succ_count`, `fail_count`, `total_count` — scrape statistics
- `json_data_dic`, `json_get_status` — shared crawl results
- `remain_list`, `again_dic` — task state
- `stop` — cancellation flag

**Impact**: Makes testing difficult, introduces race conditions in async code, prevents parallel scrape sessions.

### 4. Inline TODO Comments

~20 TODO comments across the codebase indicating known incomplete work:
- `models/types.py`: thumb should be `list[str]`, year should be removed
- `config/models.py`: `website_single` should be removed
- `config/enums.py`: EmbyAction enums need simplification, Switch enums not applicable to web
- `core/scraper.py`: tag generation should move to write_nfo, crawl results should be authoritative
- `crawlers/base/base.py`: source should use Enum directly
- `utils/__init__.py`: thread-killing C API calls should be removed in async version

### 5. Legacy `base/` Module

`mdcx/base/file.py` (33KB) and `mdcx/base/image.py` overlap with `mdcx/core/` and `mdcx/utils/`. Unclear separation of responsibilities.

## Security Considerations

### 1. CORS: Allow All Origins

```python
# server.py
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)
```

**Risk**: Any website can make authenticated requests if the user has a session. Acceptable for local dev, needs tightening for production.

### 2. SSL Verification Disabled

```python
# mdcx/web_async.py
self.curl_session = AsyncSession(verify=False, ...)
# mdcx/llm.py
AsyncClient(verify=False, ...)
```

**Risk**: Susceptible to MITM attacks. Likely necessary due to target sites' SSL issues, but the LLM client should verify SSL.

### 3. API Key in Header Only

```python
# mdcx/server/dependencies.py
api_key_header = ...  # API key transmitted in HTTP header
```

No rate limiting, no IP allowlisting, no HTTPS enforcement.

### 4. Server Listening Security

TODO in `mdcx/server/config.py`:
> "考虑任何情况下都不允许监听非本地地址, 必须使用 reverse proxy"

Currently may bind to non-localhost addresses.

## Performance Concerns

### 1. Amazon HD Image Search

`mdcx/core/amazon.py` is **76,000 lines** — an enormous file that likely contains embedded data or very complex search logic. This is the single largest source file.

### 2. No Frontend Code Splitting (Beyond Routes)

The Rsbuild config enables auto code splitting for routes via TanStack Router plugin, but the generated API client files are large (schemas.gen.ts: 47K, types.gen.ts: 30K) and may impact initial load.

### 3. Synchronous Config Manager Init

`ConfigManager.__init__()` performs file I/O synchronously at import time:
```python
manager = ConfigManager()  # Module-level, runs at import
```

This blocks the event loop on first import.

## Fragile Areas

### 1. Number Pattern Recognition

`mdcx/number.py` (11K lines) uses extensive regex patterns for video ID extraction. Brittle to edge cases; changes risk breaking existing pattern matches.

### 2. Manual Mapping Tables

`mdcx/manual.py` (32K lines) contains hardcoded actor name mappings, studio mappings, and other lookup tables. Requires manual updates.

### 3. Config V1 Migration

`mdcx/config/v1.py` (16K lines) handles `.ini` → `.json` migration. One-time code that adds complexity but is still needed for existing users.

### 4. Same-Number Deduplication

Async coordination in `Scraper.process_one_file()` uses polling (`while status is None: await sleep(1)`) rather than proper async primitives. Risk of deadlock if the first task fails silently.

## Missing Capabilities

1. **No frontend tests** — Web UI has zero test coverage
2. **No API documentation** — OpenAPI spec is generated but no manual docs
3. **No structured logging** — Uses print/emit with emoji prefixes, no log levels
4. **No database** — All state is file-based (config JSON, success lists)
5. **No i18n framework** — Hardcoded Chinese strings throughout
6. **No health check endpoint** — Server has no `/health` or readiness probe
