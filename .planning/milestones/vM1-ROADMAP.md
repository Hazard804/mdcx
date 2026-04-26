# Roadmap — MDCx JavStash Scraper (M1)

> Milestone: M1 — JavStash GraphQL Scraper
> Generated: 2026-04-26
> Status: 1 / 2 phases complete

---

## Summary

| # | Phase | Goal | Requirements | Status |
|---|-------|------|--------------|--------|
| 1 | Config & Registration | Wire the scraper into MDCx plumbing | CFG-01..03, REG-01..02 | ✅ Completed |
| 2 | GraphQL Crawler Implementation | Query javstash.org and return `CrawlerResult` | SCN-01..03, DAT-01..03, PER-01..03, TRN-01..02 | ✅ Completed |

---

## Phase 1 — Config & Registration

**Goal**: The `JAVSTASH` website option appears in MDCx with its API key and URL settings persisted in config. The crawler class is registered in the crawler registry so that Phase 2 can be tested end-to-end.

**Why first**: Everything in Phase 2 depends on the enum value, config fields, and the registry hook being in place. This phase has zero scraping logic and can be fully verified by reading config values in a test.

### Plans

#### Plan 1.1 — Config Fields

Files to change:
- `mdcx/config/enums.py` — add `JAVSTASH = "javstash"` to `Website` enum
- `mdcx/config/models.py` — add `javstash_url: str` and `javstash_api_key: str` fields to `Config`
- `mdcx/config/v1.py` — add migration defaults for both fields
- `resources/config/default_config.json` — add default values

Acceptance: `manager.config.javstash_url` and `manager.config.javstash_api_key` are accessible at runtime.

#### Plan 1.2 — Crawler Skeleton & Registration

Files to create/change:
- `mdcx/crawlers/javstash.py` — create `StashGraphQLCrawler(GenericBaseCrawler)` with a stub `_run()` that raises `NotImplementedError`
- `mdcx/crawlers/__init__.py` — import `javstash` and call `register_crawler(javstash.StashGraphQLCrawler)`

Acceptance: `get_crawler(Website.JAVSTASH)` returns the crawler class.

### Success Criteria

1. `Website.JAVSTASH` is a valid enum member with value `"javstash"`
2. `manager.config.javstash_url` returns `"https://javstash.org"` by default
3. `manager.config.javstash_api_key` returns `""` by default
4. `get_crawler(Website.JAVSTASH)` is not `None`
5. No regressions in existing crawler registry (all 4 new-style crawlers still registered)

---

## Phase 2 — GraphQL Crawler Implementation

**Goal**: `StashGraphQLCrawler.run(input)` queries `https://javstash.org/graphql`, resolves the correct scene using hash-then-number strategy, and returns a `CrawlerResponse` with a fully-populated `CrawlerResult`.

**Depends on**: Phase 1

### Plans

#### Plan 2.1 — GraphQL Transport & Auth

Implement `_post_graphql(ctx, query, variables)` helper on `StashGraphQLCrawler`:
- POSTs JSON `{"query": ..., "variables": ...}` to `{javstash_url}/graphql`
- Adds header `ApiKey: {javstash_api_key}`
- Returns parsed JSON data or raises `CralwerException` with the GraphQL error message
- Validates API key present; logs guidance if missing

#### Plan 2.2 — Scene Lookup Strategy

Override `_run(ctx)` to implement hash-first, number-fallback:

```
1. Compute oshash of ctx.input.file_path
2. POST findScenes query filtered by fingerprint (type=OSHASH, value=hash)
3. If result → go to data extraction
4. Else: POST findScenes query with q=ctx.input.number, take first result
5. If still no result → raise CralwerException("未找到匹配场景")
```

GraphQL queries to implement:
- `FIND_BY_FINGERPRINT` — `findScenes(scene_filter: {fingerprints: {value: $hash, type: OSHASH}})`
- `FIND_BY_NUMBER` — `findScenes(filter: {q: $number, per_page: 5})`
- `FIND_BY_ID` — `findScene(id: $id)` (for `appoint_url` direct-link mode)

#### Plan 2.3 — Data Mapping

Implement `_map_scene(raw_scene) -> CrawlerData`:

| Stash field | CrawlerData field | Notes |
|-------------|-------------------|-------|
| `title` | `title`, `originaltitle` | |
| `date` | `release`, `year` | year = date[:4] |
| `details` | `outline`, `originalplot` | |
| `studio.name` | `studio`, `publisher` | |
| `tags[].name` | `tag` | joined with `,` |
| `paths.screenshot` | `thumb`, `poster` | same URL for both |
| `url` | `website` | |
| `files[0].duration` | `runtime` | convert seconds → minutes |
| `performers[].name` | `actor` (female only), `all_actor` (all) | filter `gender != MALE` |
| `performers[].image_path` | `actor_photo`, `all_actor_photo` | dict keyed by name |
| `stash_ids[0].stash_id` or input number | `number` | |

### Success Criteria

1. With a valid API key and a media file whose oshash is indexed on javstash.org, `run()` returns a `CrawlerResponse` with non-empty `data.title`
2. With an unrecognized hash but a known number (e.g. `ABC-123`), the number fallback succeeds and returns a result
3. With `appoint_url` set to a valid scene URL, the direct-ID path is used and succeeds
4. With an empty `javstash_api_key`, `run()` returns a `CrawlerResponse` with `debug_info.error` containing a user-friendly message
5. Performer photo URLs are present in `data.actor_photo` for known performers
6. `runtime` is expressed in minutes (integer string)
7. No `oshash` computation crash when `file_path` is empty (guard with try/except)

---

## STATE

```
current_phase: 1
current_plan: 1.1
milestone: M1 — JavStash GraphQL Scraper
initialized: 2026-04-26
```
