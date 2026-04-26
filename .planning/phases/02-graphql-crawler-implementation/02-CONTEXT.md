# Phase 2: GraphQL Crawler Implementation - Context

**Gathered:** 2026-04-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement `StashGraphQLCrawler._run()` so it queries `{javstash_url}/graphql`, resolves the correct scene via hash-first / number-fallback / direct-ID strategies, and returns a fully-populated `CrawlerResult`. No UI changes, no new config fields — pure business logic inside `mdcx/crawlers/javstash.py`.

</domain>

<decisions>
## Implementation Decisions

### Config Access
- **D-01:** Read `manager.config.javstash_api_key` and `manager.config.javstash_url` **once at construction time** in `__init__`, storing them as `self.api_key` and `self.base_url`. Do not call `manager.config` on every request. Pattern mirrors `AvbaseCrawler` (which reads `manager.config` at use-site in `post_process`) but for the key fields that never change per-request, once-at-init is preferred.

### appoint_url / Direct-ID Parsing
- **D-02:** The canonical Stash scene URL format (confirmed from `D:/Dev/projects/stash/ui/v2.5/src/models/sceneQueue.ts`) is `/scenes/{id}` — e.g. `https://javstash.org/scenes/12345`. Extract the numeric ID from `appoint_url` using a regex: `re.search(r"/scenes/(\d+)", appoint_url)`. Treat the captured group as the GraphQL `id` argument for `findScene(id: $id)`.
- **D-03:** The GraphQL schema exposes **`findSceneByHash(input: SceneHashInput!)`** (`SceneHashInput { checksum, oshash }`) as a dedicated top-level query — use this for the hash lookup path instead of `findScenes` with a filter. This is simpler and more explicit.
- **D-04:** For the number-fallback path, use `findScenes(filter: {q: $number, per_page: 5})` and take the first result.

### Data Mapping — actor_photo pattern
- **D-05:** Follow the **ThePornDB pattern** exactly. After resolving performers, build two plain dicts:
  - `actor_photo = {name: image_path_url}` for female performers only (filter `gender != "MALE"`)
  - `all_actor_photo = {name: image_path_url}` for all performers
  These are injected into `CrawlerData` via the `external_id` field is NOT used for this — they must be surfaced through the `CrawlerResult` compat layer the same way ThePornDB does it (the legacy dict path). **Note:** `CrawlerData` has no `actor_photo` field; the planner must figure out the correct injection point consistent with how ThePornDB surfaces this to the wider pipeline.

### oshash Failure Guard
- **D-06:** Wrap the `oshash.oshash(file_path)` call in `try/except`. On failure (file missing, empty path, I/O error), **log a warning** via `ctx.debug(f"⚠️ oshash 计算失败，跳过哈希搜索: {e}")` and fall through silently to the number-fallback path. Do not raise or abort.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### GraphQL Schema (Stash)
- `D:/Dev/projects/stash/graphql/schema/schema.graphql` — Top-level queries: `findScene(id: ID)`, `findSceneByHash(input: SceneHashInput!)`, `findScenes(filter: FindFilterType, scene_filter: SceneFilterType)`
- `D:/Dev/projects/stash/graphql/schema/types/scene.graphql` — `Scene` type: `id`, `title`, `code`, `details`, `date`, `urls`, `studio`, `tags`, `performers`, `stash_ids`, `paths`, `files` (duration via `VideoFile.duration`)
- `D:/Dev/projects/stash/graphql/schema/types/file.graphql` — `SceneHashInput { checksum, oshash }` at line 264 of scene.graphql; `VideoFile.duration: Float` (seconds)
- `D:/Dev/projects/stash/graphql/schema/types/filters.graphql` — `FindFilterType { q, per_page }` for number-fallback; `SceneFilterType.oshash` (not used — replaced by `findSceneByHash`)

### Stash URL Format
- `D:/Dev/projects/stash/ui/v2.5/src/models/sceneQueue.ts` line 123 — confirms scene URL pattern: `/scenes/${sceneID}`

### Crawler Infrastructure
- `mdcx/crawlers/base/base.py` — `GenericBaseCrawler.__init__` signature; `run()` orchestrator; `CralwerException`
- `mdcx/crawlers/base/types.py` — `CrawlerData` dataclass (fields available: `title`, `originaltitle`, `actors`, `all_actors`, `outline`, `originalplot`, `studio`, `publisher`, `tags`, `thumb`, `poster`, `release`, `year`, `runtime`, `number`, `external_id`, `source`, `website`)
- `mdcx/crawlers/javstash.py` — Phase 1 stub being replaced
- `mdcx/crawlers/theporndb.py` — Reference for hash lookup flow, `actor_photo` / `all_actor_photo` dict pattern, and oshash guard

### HTTP Transport
- `mdcx/web_async.py` lines 932–952 — `AsyncWebClient.post_json(url, *, json_data, headers)` — use this for all GraphQL POSTs

### Config
- `mdcx/config/models.py` line 629 — `Config.javstash_api_key`; line ~630 — `Config.javstash_url`
- `mdcx/config/manager.py` — `manager` singleton import pattern

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `AsyncWebClient.post_json(url, *, json_data, headers)` — ready to POST `{"query": ..., "variables": ...}` to the GraphQL endpoint with the `ApiKey` header
- `oshash` library — already imported and used in `theporndb.py`; same import pattern applies
- `CralwerException` from `mdcx/crawlers/base/types.py` — raise this for user-visible scraping failures

### Established Patterns
- **`_run()` full override**: `StashGraphQLCrawler` overrides `_run()` completely (not `_generate_search_url` + `_parse_search_page` + `_parse_detail_page`). The abstract HTML-based methods remain raising `NotImplementedError` — they are never called.
- **Constructor access**: `self.api_key = manager.config.javstash_api_key` in `__init__` (after calling `super().__init__(client, base_url)`). For `base_url`, the constructor already does `self.base_url = base_url or self.base_url_()`.
- **`CrawlerData` field names**: Use `actors` (list), `all_actors` (list), `tags` (list), `runtime` (str in minutes), `thumb` and `poster` (both same screenshot URL from `paths.screenshot`).
- **`external_id`**: Set to the scene's Stash integer ID (as string) — used for dedup.

### Integration Points
- `mdcx/crawlers/javstash.py` — sole file to modify in Phase 2 (the Phase 1 stub becomes the full implementation)
- `mdcx/config/manager.py` — `manager` import at module level (already in file or add it)
- No changes to `__init__.py`, `models.py`, or any other file — Phase 2 is purely `javstash.py`

</code_context>

<specifics>
## Specific Ideas

- Use `findSceneByHash` (not `findScenes` with filter) for hash lookup — cleaner API, confirmed in schema
- Scene URL regex: `re.search(r"/scenes/(\d+)", appoint_url)` — extract numeric ID, pass to `findScene(id: id_str)`
- `actor_photo` dict: `{performer_name: performer.image_path}` — `image_path` is the GraphQL field (confirmed from stash performer schema — verify exact field name during planning)
- Runtime conversion: `str(int(duration_seconds / 60))` — matches ThePornDB pattern exactly
- Warning log format for oshash failure: `ctx.debug(f"⚠️ oshash 计算失败，跳过哈希搜索: {e}")` then continue to number search

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 2-GraphQL Crawler Implementation*
*Context gathered: 2026-04-26*
