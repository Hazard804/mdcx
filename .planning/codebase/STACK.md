# Technology Stack

> Last mapped: 2026-04-26

## Languages

| Language   | Version    | Usage                              |
|------------|------------|------------------------------------|
| Python     | ≥ 3.13.4   | Backend, crawlers, desktop GUI, CLI |
| TypeScript | ≥ 5.9      | Web UI frontend                    |
| JavaScript | (via TS)   | Build tooling                      |

## Runtime & Package Managers

| Tool   | Role                          | Config File           |
|--------|-------------------------------|-----------------------|
| uv     | Python dependency/venv manager | `pyproject.toml`, `uv.lock` |
| pnpm   | Node package manager (UI)     | `ui/pnpm-lock.yaml`, `ui/pnpm-workspace.yaml` |

## Python Dependencies (Core)

| Package                          | Version       | Purpose                                 |
|----------------------------------|---------------|-----------------------------------------|
| `pyqt5`                         | 5.15.11       | Desktop GUI framework                   |
| `fastapi`                       | ≥ 0.116.1     | Web API server (optional extra `[web]`)  |
| `uvicorn[standard]`             | ≥ 0.35.0      | ASGI server for FastAPI                  |
| `curl-cffi`                     | 0.11.4        | HTTP client with browser impersonation   |
| `httpx[socks]`                  | ≥ 0.28.1      | HTTP client (proxy/socks support)        |
| `aiofiles`                      | 24.1.0        | Async file I/O                           |
| `aiolimiter`                    | 1.2.1         | Async rate limiting                      |
| `beautifulsoup4`                | 4.13.4        | HTML parsing (legacy crawlers)           |
| `lxml`                          | ≥ 5.2.0       | XML/HTML parsing                         |
| `parsel`                        | ≥ 1.10.0      | CSS/XPath selector (new crawlers)        |
| `openai`                        | 1.91.0        | LLM API client for translation           |
| `pydantic-settings`             | ≥ 2.10.1      | Config modeling & validation             |
| `pillow`                        | 11.3.0        | Image processing (watermarks, crops)     |
| `opencv-contrib-python-headless`| 4.13.0.92     | Video processing (resolution detection)  |
| `av`                            | ≥ 15.0.0      | Video metadata extraction (PyAV)         |
| `zhconv`                        | 1.4.3         | Simplified/Traditional Chinese conversion|
| `oshash`                        | 0.1.1         | File hashing (OpenSubtitles hash)        |
| `ping3`                         | 4.0.4         | Network connectivity checks              |

## Python Dependencies (Dev)

| Package           | Purpose                        |
|-------------------|--------------------------------|
| `pytest`          | Test framework                 |
| `pytest-asyncio`  | Async test support             |
| `pytest-cov`      | Coverage reporting             |
| `ruff`            | Linter & formatter             |
| `pre-commit`      | Git hooks                      |
| `pyinstaller`     | Desktop app packaging          |
| `typer`           | CLI framework (scripts)        |
| `rich`            | CLI output formatting          |
| `ipykernel`       | Jupyter kernel (dev notebooks) |

## Frontend Dependencies (UI)

| Package                         | Purpose                               |
|---------------------------------|---------------------------------------|
| React 19                        | UI framework                          |
| `@mui/material` 7.x             | Component library (MUI v7)            |
| `@emotion/react` + `@emotion/styled` | CSS-in-JS for MUI                |
| `@tanstack/react-router`        | File-based routing                    |
| `@tanstack/react-query`         | Data fetching & caching               |
| `zustand`                       | Global state management               |
| `@rjsf/core` (v6 beta)         | JSON Schema forms (config UI)         |
| `@dnd-kit/*`                    | Drag-and-drop                         |
| `axios`                         | HTTP client                           |
| `usehooks-ts`                   | React utility hooks                   |

## Frontend Dev Tooling

| Tool                   | Purpose                    | Config File             |
|------------------------|----------------------------|-------------------------|
| Rsbuild                | Build tool (Rspack-based)  | `ui/rsbuild.config.ts`  |
| Biome                  | Linter + formatter         | `ui/biome.json`         |
| TypeScript 5.9         | Type checking              | `ui/tsconfig.json`      |
| `@hey-api/openapi-ts`  | API client codegen         | `ui/openapi-ts.config.ts` |
| TanStack Router Plugin | Auto route generation      | (in rsbuild config)     |

## Build & Distribution

- **Desktop (Qt)**: PyInstaller bundles into standalone executable
- **Web Server**: FastAPI serves API + static UI (`ui/dist/`)
- **CI/CD**: GitHub Actions (`ci.yaml`, `release.yml`, `release.v1.yml`)
- **Pre-commit**: ruff check + ruff format on pre-merge-commit and pre-push

## Configuration Files

| File                    | Purpose                                  |
|-------------------------|------------------------------------------|
| `pyproject.toml`        | Python project metadata & dependencies   |
| `ruff.toml`             | Python linter/formatter rules            |
| `.pre-commit-config.yaml` | Git hooks configuration               |
| `ui/biome.json`         | JS/TS linter/formatter rules             |
| `ui/tsconfig.json`      | TypeScript compiler options              |
| `ui/rsbuild.config.ts`  | Frontend build configuration             |
| `ui/openapi-ts.config.ts` | OpenAPI client generation config       |
| `mdcx.code-workspace`  | VS Code multi-root workspace             |

## Platform Support

Configured in `pyproject.toml` via `tool.uv.required-environments`:
- Linux x86_64
- macOS x86_64 + ARM64
- Windows AMD64

PyQt5 wheel pinning differs by platform (`5.15.2` on Windows, `5.15.17` elsewhere).
