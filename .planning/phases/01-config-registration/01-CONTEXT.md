# Phase 1: Config & Registration - Context

**Gathered:** 2026-04-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the `JAVSTASH` website option into MDCx's enum, config model, V1 migration defaults, default config JSON, and crawler registry. No scraping logic — this is pure plumbing so Phase 2 can be tested end-to-end.

</domain>

<decisions>
## Implementation Decisions

### Field Priority Lists
- **D-01:** `Website.JAVSTASH` MUST be added to all `site_prority` default lists in `FieldConfig` (in `mdcx/config/models.py`) for every field that the JavStash GraphQL data can populate. Based on Phase 2's data mapping, JAVSTASH provides: `title`, `originaltitle`, `release`, `year`, `outline`, `originalplot`, `studio`, `publisher`, `tag`, `thumb`, `poster`, `website`, `runtime`, `actor`, `actor_photo`, `number`. Add JAVSTASH to the priority lists for all of these fields.
- **D-02:** Position JAVSTASH after `THEPORNDB` in the priority lists (follow existing ordering convention).

### Config Field Naming & Validation
- **D-03:** API key field title: `"StashAPI 令牌"` (matches the bilingual convention used by other fields like `"Theporndb API令牌"`).
- **D-04:** `javstash_url` field gets a Pydantic validator that tests connectivity to the GraphQL endpoint using the API key. This validates that the URL is reachable and the key is accepted — not just format validation.
- **D-05:** Default URL: `"https://javstash.org"`. Default API key: `""` (empty string).

### Stub Crawler Behavior
- **D-06:** `StashGraphQLCrawler._run()` raises `NotImplementedError` in the Phase 1 skeleton. This makes it clear the crawler is registered but not functional until Phase 2.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Config System
- `mdcx/config/enums.py` — `Website` enum definition (line 489+). Add `JAVSTASH` entry here.
- `mdcx/config/models.py` — `Config` Pydantic model. `theporndb_api_token` at line 628 is the pattern for API key fields. `FieldConfig` `site_prority` lists at lines 370-442 are where JAVSTASH joins.
- `mdcx/config/v1.py` — V1 migration defaults. `theporndb_api_token` at line 281 is the pattern.
- `resources/config/default_config.json` — Default config values template.

### Crawler System
- `mdcx/crawlers/base/base.py` — `GenericBaseCrawler` base class and `register_crawler()` function (line 210).
- `mdcx/crawlers/__init__.py` — Crawler imports and registration calls (lines 45, 90-93).
- `mdcx/crawlers/missav.py` — Reference for single-file new-style crawler (simplest example).

### Stash Reference
- `D:/Dev/projects/stash/graphql/schema/schema.graphql` — Stash GraphQL schema (for understanding available fields).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `theporndb_api_token` field pattern in `Config` — exact template for adding `javstash_api_key` and `javstash_url`
- `Switch.THEPORNDB_NO_HASH` enum — may want an analogous switch for JAVSTASH hash behavior later (not Phase 1)

### Established Patterns
- **Enum convention**: `Website` enum has no `names()` classmethod — just `NAME = "value"` entries
- **Config field convention**: `Field(default="", title="Chinese Title")` with Pydantic
- **V1 migration**: Plain string defaults in the V1 dataclass, auto-migrated to V2 JSON
- **Registration**: `register_crawler(CrawlerClass)` at module level in `__init__.py`

### Integration Points
- `mdcx/config/enums.py` line 525+ — add `JAVSTASH` after `THEPORNDB`
- `mdcx/config/models.py` line 628+ — add `javstash_api_key` and `javstash_url` fields near `theporndb_api_token`
- `mdcx/config/models.py` lines 370-442 — add `Website.JAVSTASH` to relevant `site_prority` lists
- `mdcx/crawlers/__init__.py` lines 90-93 — add `register_crawler(StashGraphQLCrawler)` after existing registrations
- New file: `mdcx/crawlers/javstash.py` — stub crawler class

</code_context>

<specifics>
## Specific Ideas

- API key field title must be exactly `"StashAPI 令牌"` — user-specified
- URL validator should test actual GraphQL endpoint connectivity, not just URL format
- Follow the `theporndb` pattern closely for config field placement and naming

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 1-Config & Registration*
*Context gathered: 2026-04-26*
