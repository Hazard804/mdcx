# Conventions

> Last mapped: 2026-04-26

## Code Style

### Python

- **Formatter/Linter**: Ruff (configured in `ruff.toml`)
- **Line length**: 120 characters
- **Indent**: 4 spaces
- **Quotes**: Double quotes
- **Import order**: isort (`I` rules)
- **Rules enabled**: pycodestyle (E), Pyflakes (F), flake8-bugbear (B), flake8-comprehensions (C4), pyupgrade (UP), FastAPI (FAST), select async rules (ASYNC230, ASYNC251)
- **Ignored**: E501 (line length — enforced only by formatter), B005, B007, B904, SIM113
- **Pre-commit hooks**: `ruff check --fix` + `ruff format` on pre-merge-commit and pre-push

### TypeScript/JavaScript

- **Formatter/Linter**: Biome (configured in `ui/biome.json`)
- **Module system**: ESNext with `verbatimModuleSyntax`
- **Strict mode**: Enabled (`noUnusedLocals`, `noUnusedParameters`)
- **Path aliases**: `@/*` → `src/*`

## Naming Conventions

### Python

| Element          | Convention         | Example                           |
|------------------|--------------------|------------------------------------|
| Files            | snake_case         | `web_async.py`, `file_crawler.py`  |
| Classes          | PascalCase         | `AsyncWebClient`, `CrawlerProvider`|
| Functions        | snake_case         | `get_file_info_v2()`, `add_mark()` |
| Constants        | UPPER_SNAKE        | `MAIN_PATH`, `IS_WINDOWS`          |
| Enums            | PascalCase class, UPPER values | `Website.JAVBUS`      |
| Private methods  | Leading underscore | `_run()`, `_fetch_search()`        |
| Generated files  | `*_generated.py`   | Excluded from ruff                 |

### TypeScript

| Element          | Convention         | Example                         |
|------------------|--------------------|----------------------------------|
| Files            | camelCase/PascalCase | `useWebSocket.ts`, `Layout.tsx`|
| Components       | PascalCase         | `FileBrowser`, `WebSocketStatus` |
| Hooks            | `use` prefix       | `useTheme`, `useWebSocket`       |
| Store files      | camelCase          | `logStore.ts`                    |
| Routes           | lowercase          | `settings.tsx`, `logs.tsx`       |
| Generated files  | `*.gen.ts`         | `types.gen.ts`, `sdk.gen.ts`     |

## Code Patterns

### Singleton Pattern

Config manager uses module-level singleton:
```python
# mdcx/config/manager.py
manager = ConfigManager()  # Created at import time
```

Signals use decorator singleton:
```python
# mdcx/signals.py
@singleton
class Signals(QObject): ...
signal_qt = Signals()
```

### Dataclass Pattern (Domain Models)

All domain types use `@dataclass` with `empty()` factory methods:
```python
@dataclass
class FileInfo:
    number: str
    mosaic: str
    # ...
    @classmethod
    def empty(cls) -> "FileInfo":
        return cls(number="", mosaic="", ...)
```

### Pydantic Pattern (Config Models)

Config uses Pydantic with `Field()` annotations including Chinese `title`:
```python
class Config(BaseModel):
    thread_number: int = Field(default=50, title="并发数")
    website_youma: set[Website] = Field(default_factory=lambda: {...}, title="有码网站源")
```

### Enum Pattern

Custom `Enum` base class (in `mdcx/config/ui_schema.py`) with `names()` classmethod providing Chinese display names:
```python
class Website(Enum):
    JAVBUS = "javbus"
    DMM = "dmm"
    # ...
```

### Crawler Pattern (New-Style)

Template method with generic context:
```python
class DmmCrawler(GenericBaseCrawler[DmmContext]):
    @classmethod
    def site(cls) -> Website: return Website.DMM

    @classmethod
    def base_url_(cls) -> str: return "https://..."

    def new_context(self, input): return DmmContext(input=input)

    async def _generate_search_url(self, ctx): ...
    async def _parse_search_page(self, ctx, html, url): ...
    async def _parse_detail_page(self, ctx, html, url): ...
```

### Signal/Event Pattern

Both Qt and Server signals share the same interface:
```python
signal.show_log_text("message")
signal.exec_set_processbar.emit(50)
signal.show_list_name("succ", show_data, number)
```

### Error Handling

- Crawlers: Exceptions caught in `run()`, stored in `CrawlerDebugInfo.error`
- Scraper: Per-file try/except with `traceback.format_exc()` logging
- Config: Validation errors collected and returned as `list[str]`
- HTTP: Retry with backoff (`_calc_retry_sleep_seconds`)
- Pattern: Never crash on individual file failure; log and continue

### Async Patterns

```python
# Rate-limited requests
async with limiter.acquire():
    response = await self.curl_session.request(...)

# Bounded concurrency (manual task pool)
async def _run_tasks_with_limit(self, movie_list, task_count, thread_number):
    # Submit up to thread_number tasks, replace completed ones
```

## Language & Comments

- **Comments**: Primarily Chinese (Simplified), matching the target audience
- **Docstrings**: Mix of Chinese and English
- **Variable names**: English, but some legacy names have abbreviated Chinese phonetics
- **UI labels**: All Chinese, defined in enum `names()` classmethods
- **Log messages**: Chinese with emoji prefixes (🕷, 🔴, 🎉, ⏰, etc.)
