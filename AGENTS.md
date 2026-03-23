# AGENTS.md

## 默认工作约定

- 默认使用简体中文沟通，推送到远端的说明也使用中文。（除非用户明确要求其他语言）。
- 在 Windows 环境下，命令执行优先使用 `pwsh.exe`（PowerShell 7），不要默认使用 `powershell.exe`（5.1）。

## 编码约定（必须遵守）

- 所有文本读取/写入默认使用 UTF-8，避免中文乱码。
- 读取文件时显式指定编码：`Get-Content -Encoding UTF8`。
- 写入文件时显式指定编码：`Set-Content/Add-Content/Out-File -Encoding UTF8`。
- 如需在终端输出中文，先确保控制台编码为 UTF-8：
  - `[Console]::InputEncoding  = [System.Text.UTF8Encoding]::new($false)`
  - `[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)`
  - `$OutputEncoding = [System.Text.UTF8Encoding]::new($false)`

## 开发与提交流程约定（必须遵守）

- 新增爬虫时，优先复用 `crawlers` 目录内已有的基础接口与基类，避免重复造轮子。
- 当用户明确要求“提交到远端”时，提交前必须先执行并通过 `ruff format` 与 `ruff check`。并且注意排除与项目本身无关的文件。
- 新增业务逻辑时，撰写必要的注释，并且需在关键逻辑节点补充日志输出，注释与日志的风格必须与现有代码保持一致。
- 默认采用最小修改原则，优先定位并修复根本问题，避免无关改动。
- 除非用户说明直接修改，否则在用户要求修改代码时，先输出修改方案、逻辑要点给用户审阅。
- 提交代码时，必须遵循 Conventional Commits 规范撰写提交说明，格式为 `<类型>: <描述>`。常用类型如下：
  - **feat**: 新增功能。
  - **fix**: 修复 Bug。
  - **docs**: 文档变更。
  - **style**: 代码格式调整（不影响逻辑）。
  - **refactor**: 代码重构。
  - **chore**: 构建过程或辅助工具的变动。

## 发布新版流程约定（必须遵守）

- 当用户明确要求“发布新版”“发版”“推送新版到远端”时，视为需要执行完整发版流程，而不是只修改本地代码。
- 当前项目发布版本号以 `mdcx/consts.py` 中的 `LOCAL_VERSION` 为准；发布时使用的 Git tag 必须与该值完全一致。
- 当前项目用于触发 GitHub Actions `Build and Release with Python3.13` 的 tag 格式为纯数字版本号，且需匹配 `220*`；不要使用 `v220xxxxxx`、`feat-220xxxxxx`、`fix-220xxxxxx` 等格式。
- 当用户要求发布新版时，如未明确指定目标版本号，应先检查并确认 `LOCAL_VERSION` 是否已更新到目标版本；如未更新，应先修改版本号再继续后续发布流程。
- 当用户明确要求发布新版或推送到远端时，提交前必须先执行并通过 `ruff format` 与 `ruff check`，并注意排除与项目本身无关的文件。
- 发布新版时，提交说明仍需遵循 Conventional Commits，发布场景默认优先使用 `chore: release <版本号>`；如果本次仅提升版本号，也优先使用该格式。
- 发布新版的标准执行顺序为：确认或更新 `LOCAL_VERSION`、执行 `ruff format`、执行 `ruff check`、提交相关文件、创建与 `LOCAL_VERSION` 一致的 tag、推送分支、推送 tag。
- 若 `LOCAL_VERSION` 与待创建 tag 不一致，或 tag 不符合 `220*` 规则，不得继续推送远端，必须先修正。
- 普通的 commit push 即使修改了 `LOCAL_VERSION`，当前默认也不会自动触发发布；只有推送匹配规则的 tag、发布 GitHub Release 或手动触发 workflow 才会执行自动打包。
