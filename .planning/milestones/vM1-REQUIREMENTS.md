# Requirements — MDCx JavStash Scraper (M1)

> Generated: 2026-04-26
> Milestone: M1 — JavStash GraphQL Scraper

---

## v1 Requirements

### Config Integration

- [x] **CFG-01**: User can enter a `javstash_url` (default `https://javstash.org`) in MDCx Network settings
- [x] **CFG-02**: User can enter a `javstash_api_key` in MDCx Network settings (stored as plain string, same as `theporndb_api_token`)
- [x] **CFG-03**: Scraper shows a clear error log message if API key is missing, guiding the user to settings

### Crawler Registration

- [x] **REG-01**: `Website.JAVSTASH` enum value added to `mdcx/config/enums.py`
- [x] **REG-02**: `StashGraphQLCrawler` registered in `mdcx/crawlers/__init__.py` via `register_crawler()`

### Scene Lookup

- [x] **SCN-01**: Crawler attempts hash lookup first — computes `oshash` of the local file and queries `findScenes(scene_filter: {fingerprints: {value: $hash, type: OSHASH}})` 
- [x] **SCN-02**: If hash lookup returns no result, crawler falls back to keyword search using the parsed scene number (e.g. `ABC-123`) via `findScenes(filter: {q: $number})`
- [x] **SCN-03**: If `appoint_url` is provided (user-specified URL), crawler skips lookup and fetches that scene ID directly via `findScene(id: $id)`

### Data Extraction — Scene

- [x] **DAT-01**: Crawler extracts and maps: `title`, `date` (→ `release`/`year`), `studio.name` (→ `studio`/`publisher`), `details` (→ `outline`), `tags[].name` (→ `tag`), `paths.screenshot` (→ `thumb`/`poster`), `url` (→ `website`)
- [x] **DAT-02**: Crawler extracts `runtime` in minutes from scene `files[0].duration`
- [x] **DAT-03**: Crawler populates `number` from the scene's first `stash_ids[].stash_id` if present, otherwise falls back to the original search number

### Data Extraction — Performers

- [x] **PER-01**: Crawler extracts `performers[].name` joined as comma-separated string (→ `actor`)
- [x] **PER-02**: Crawler extracts `performers[].image_path` (→ `actor_photo` dict keyed by performer name)
- [x] **PER-03**: Female performers are preferred for `actor`; all performers go into `all_actor` (filter by `performers[].gender != MALE`)

### Transport / Auth

- [x] **TRN-01**: All GraphQL requests are POSTed to `{javstash_url}/graphql` with header `ApiKey: {javstash_api_key}`
- [x] **TRN-02**: GraphQL errors returned in the `errors` field of the response are caught and logged as debug info

---

## v2 Requirements (deferred)

- Studio scraper (`findStudios`) — add studio aliases and network hierarchy
- Support filtering by `performers[].gender` more precisely (currently Stash uses `FEMALE`/`MALE`/`TRANSGENDER_FEMALE`/etc.)
- Support for user-hosted private Stash instances beyond javstash.org
- Batch fingerprint submission (`submitStashBoxFingerprints`) — future contribution flow

---

## Out of Scope (M1)

- **Any write mutations** — read-only scraping only; `sceneCreate`, `sceneUpdate`, etc. are never called
- **Gallery / image scraping** — MDCx does not have a gallery concept
- **DLNA / plugin API** — irrelevant to the scraper layer
- **Stash-box submission** — out of scope for a downstream fork's scraper

---

## Traceability

| REQ-ID | Phase | Plan |
|--------|-------|------|
| CFG-01, CFG-02, CFG-03 | Phase 1 | Plan 1.1 |
| REG-01, REG-02 | Phase 1 | Plan 1.2 |
| SCN-01, SCN-02, SCN-03 | Phase 2 | Plan 2.1 |
| DAT-01, DAT-02, DAT-03 | Phase 2 | Plan 2.2 |
| PER-01, PER-02, PER-03 | Phase 2 | Plan 2.3 |
| TRN-01, TRN-02 | Phase 2 | Plan 2.1 |
