# Directory Structure

> Last mapped: 2026-04-26

## Root Layout

```
mdcx-from-hazard804/
├── main.py                    # Desktop GUI entry point (PyQt5)
├── server.py                  # Web server entry point (FastAPI)
├── pyproject.toml             # Python project config & dependencies
├── uv.lock                    # Locked Python dependencies
├── ruff.toml                  # Python linter/formatter config
├── .pre-commit-config.yaml    # Git hooks (ruff check + format)
├── .gitignore
├── README.md                  # Project README (Chinese)
├── CONTRIBUTING.md            # Dev setup & code structure guide
├── LICENSE                    # GPLv3
├── changelog.md               # Release notes
├── todo.md                    # Project-level TODOs
├── mdcx.code-workspace        # VS Code multi-root workspace
│
├── mdcx/                      # Python source code (main package)
├── ui/                        # Web UI frontend (React/TypeScript)
├── tests/                     # Python test suite
├── scripts/                   # Build & dev utility scripts
├── resources/                 # Static data files (configs, images, mappings)
├── libs/                      # Bundled native libraries (OpenSSL DLLs)
├── .github/                   # GitHub Actions workflows & issue templates
└── .planning/                 # GSD planning directory
```

## Python Source: `mdcx/`

```
mdcx/
├── __init__.py
├── consts.py              # Runtime constants (version, paths, platform flags)
├── signals.py             # Qt signal system + swap mechanism
├── crawler.py             # CrawlerProvider (lazy per-site instance management)
├── web_async.py           # AsyncWebClient (curl_cffi + CF bypass, 1104 lines)
├── llm.py                 # LLM client (OpenAI SDK wrapper)
├── number.py              # Video ID pattern recognition (11K lines)
├── manual.py              # Manual config/mapping tables (32K lines)
├── image.py               # Image utilities (crop, compare)
├── browser.py             # Browser support stub
│
├── config/                # Configuration management
│   ├── models.py          # Config Pydantic model (~983 lines, ALL settings)
│   ├── manager.py         # ConfigManager singleton (load/save/migrate)
│   ├── enums.py           # Config enum types (Website, Language, etc.)
│   ├── computed.py        # Derived computed values from config
│   ├── extend.py          # Extended config helpers (path settings)
│   ├── v1.py              # V1 .ini config migration
│   ├── resources.py       # Resource path management
│   ├── ui_schema.py       # JSON Schema UI annotations for web forms
│   └── jhs.js             # JavaScript helper for config
│
├── core/                  # Core business logic
│   ├── __init__.py
│   ├── scraper.py         # Scraper orchestrator (962 lines, main pipeline)
│   ├── file_crawler.py    # FileScraper (per-file multi-site crawling)
│   ├── file.py            # File operations (info extraction, output naming)
│   ├── web.py             # Image/trailer download logic
│   ├── nfo.py             # NFO XML generation
│   ├── image.py           # Watermark application
│   ├── translate.py       # Translation pipeline
│   ├── utils.py           # Core utility functions
│   └── amazon.py          # Amazon HD image search (76K lines)
│
├── crawlers/              # Site-specific crawlers (44 files + 2 subdirs)
│   ├── __init__.py        # Crawler registry & imports
│   ├── base/              # Crawler base classes & framework
│   │   ├── base.py        # GenericBaseCrawler[T] (new-style)
│   │   ├── compat.py      # LegacyCrawler adapter (v1 compat)
│   │   ├── parser.py      # Common parsing utilities
│   │   └── types.py       # Context, CrawlerData types
│   ├── dmm_new/           # DMM crawler (new-style, multi-file)
│   ├── javdb_new.py       # JavDB crawler (new-style)
│   ├── avbase_new.py      # Avbase crawler (new-style)
│   ├── missav.py          # MissAV crawler (new-style)
│   └── [31 legacy crawlers] # javbus.py, fc2.py, theporndb.py, etc.
│
├── models/                # Data models & types
│   ├── types.py           # Core types: FileInfo, CrawlerResult, CrawlersResult, etc.
│   ├── enums.py           # FileMode enum
│   ├── flags.py           # Global mutable state (Flags singleton)
│   ├── log_buffer.py      # Thread-local log buffer
│   └── emby.py            # Emby data types
│
├── controllers/           # Qt UI controllers
│   ├── cut_window.py      # Image crop tool controller
│   └── main_window/       # Main window controller
│       ├── main_window.py # Main controller (160K lines!)
│       ├── init.py        # Signal/event binding
│       ├── load_config.py # Config → UI binding (57K lines)
│       ├── save_config.py # UI → Config saving (41K lines)
│       ├── style.py       # Qt stylesheet (33K lines)
│       ├── handlers.py    # Event handlers
│       └── bind_utils.py  # UI binding utilities
│
├── views/                 # Qt UI definitions
│   ├── MDCx.ui            # Main window UI definition (1.2MB XML)
│   ├── MDCx.py            # Generated Python from UI (872K lines)
│   ├── posterCutTool.ui   # Image crop tool UI
│   ├── posterCutTool.py   # Generated Python from UI
│   └── CustomClass.py     # Custom Qt widget classes
│
├── server/                # Web server components
│   ├── var.py             # Server mode flag
│   ├── config.py          # Server-specific config (safe dirs, auth)
│   ├── dependencies.py    # FastAPI dependencies (API key auth)
│   ├── signals.py         # ServerSignals (Qt signal → WebSocket)
│   ├── api/v1/            # REST API endpoints
│   │   ├── __init__.py    # Router assembly
│   │   ├── config.py      # Config CRUD endpoints
│   │   ├── files.py       # File browser endpoints
│   │   ├── legacy.py      # Legacy scrape trigger endpoints
│   │   ├── utils.py       # API utilities
│   │   └── ws.py          # WebSocket endpoint
│   └── ws/                # WebSocket infrastructure
│       ├── auth.py        # WS bearer token middleware
│       ├── manager.py     # WebSocketManager (broadcast)
│       └── types.py       # WS message types
│
├── tools/                 # Standalone tools
│   ├── emby_actor_image.py  # Emby actor photo management
│   ├── emby_actor_info.py   # Emby actor info management
│   ├── actress_db.py        # Actress database queries
│   ├── missing.py           # Missing file detection
│   ├── subtitle.py          # Subtitle management
│   └── wiki.py              # Wiki data fetching
│
├── utils/                 # General utilities
│   ├── __init__.py        # Misc utils (17K lines)
│   ├── file.py            # File I/O utilities
│   ├── web.py             # Legacy sync/async web helpers (43K lines)
│   ├── web_sync.py        # Synchronous web utilities
│   ├── image.py           # Image utilities
│   ├── video.py           # Video backend detection
│   ├── translate.py       # Translation utilities
│   ├── language.py        # Language detection
│   ├── path.py            # Path utilities
│   ├── dataclass.py       # Dataclass helpers
│   └── gather_group.py    # Async gather utilities
│
├── base/                  # Legacy base modules
│   ├── file.py            # File operations (33K lines)
│   └── image.py           # Image operations
│
├── cmd/                   # CLI commands
│   ├── crawl.py           # CLI scrape command (typer)
│   └── gen_enums.py       # Enum code generation
│
└── gen/                   # Generated code
    └── field_enums.py     # Auto-generated CrawlerResultFields enum
```

## Web UI: `ui/`

```
ui/
├── package.json           # Node dependencies & scripts
├── pnpm-lock.yaml
├── pnpm-workspace.yaml
├── rsbuild.config.ts      # Rsbuild config (Rspack + React + TanStack Router)
├── tsconfig.json
├── biome.json             # Biome linter/formatter config
├── openapi-ts.config.ts   # OpenAPI client generation config
├── .env.example
│
└── src/
    ├── index.tsx           # React entry point
    ├── App.tsx             # App root (QueryClient, Router)
    ├── App.css
    ├── env.d.ts            # Environment type declarations
    ├── routeTree.gen.ts    # Auto-generated route tree
    │
    ├── routes/             # File-based routes (TanStack Router)
    │   ├── __root.tsx      # Root layout
    │   ├── index.tsx       # Home / scrape page
    │   ├── settings.tsx    # Settings page
    │   ├── logs.tsx        # Log viewer
    │   ├── tool.tsx        # Tools page
    │   ├── network.tsx     # Network settings
    │   ├── auth.tsx        # Authentication
    │   └── about.tsx       # About page
    │
    ├── components/         # Reusable components
    │   ├── Layout.tsx      # Main layout
    │   ├── FileBrowser.tsx  # File browser component
    │   ├── WebSocketStatus.tsx
    │   └── form/           # Form components
    │
    ├── client/             # Auto-generated API client
    │   ├── types.gen.ts    # Generated types (30K)
    │   ├── schemas.gen.ts  # Generated schemas (47K)
    │   ├── sdk.gen.ts      # Generated SDK (13K)
    │   ├── client.gen.ts
    │   ├── index.ts
    │   ├── @tanstack/      # Generated TanStack Query hooks
    │   ├── client/         # Client configuration
    │   └── core/           # Core client utilities
    │
    ├── store/              # Zustand state stores
    │   └── logStore.ts     # Log state management
    │
    ├── hooks/              # Custom React hooks
    │   ├── useWebSocket.ts # WebSocket connection hook
    │   └── useTheme.ts     # Theme hook
    │
    └── contexts/           # React contexts
        ├── ThemeProvider.tsx
        ├── ToastProvider.tsx
        └── WebSocketProvider.tsx
```

## Key Locations

| Need to...                        | Look at                                    |
|-----------------------------------|--------------------------------------------|
| Add a new crawler                 | `mdcx/crawlers/base/base.py` (new-style)   |
| Add a config field                | `mdcx/config/models.py`                    |
| Change the scrape pipeline        | `mdcx/core/scraper.py`                     |
| Add an API endpoint               | `mdcx/server/api/v1/`                      |
| Add a UI page                     | `ui/src/routes/`                            |
| Modify file naming/output         | `mdcx/core/file.py`                        |
| Change NFO format                 | `mdcx/core/nfo.py`                         |
| Add a translation service         | `mdcx/core/translate.py`                   |
| Update the Qt GUI                 | `mdcx/views/MDCx.ui` → `scripts/pyuic.sh` |
