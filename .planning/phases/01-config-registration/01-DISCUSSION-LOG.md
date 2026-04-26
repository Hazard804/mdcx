# Phase 1: Config & Registration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-26
**Phase:** 1-Config & Registration
**Areas discussed:** Field priority lists, Config field naming & validation, Stub crawler behavior

---

## Field Priority Lists

| Option | Description | Selected |
|--------|-------------|----------|
| Join all applicable fields | Add JAVSTASH to every `site_prority` list where the GraphQL data provides that field | ✓ |
| Stay out until Phase 2 proves quality | Keep JAVSTASH out of priority lists until data quality is verified | |
| Join only core fields | Add to title/actor/thumb only | |

**User's choice:** Join all applicable fields — JAVSTASH should appear in every priority list for fields it can provide data for.
**Notes:** Based on Phase 2's data mapping, JAVSTASH provides: title, originaltitle, release, year, outline, originalplot, studio, publisher, tag, thumb, poster, website, runtime, actor, actor_photo, number.

---

## Config Field Naming & Validation

| Option | Description | Selected |
|--------|-------------|----------|
| Plain string, no validation | Simple string field like `theporndb_api_token` | |
| URL format validator | Pydantic validator checking URL format only | |
| Connectivity validator | Validator that tests actual GraphQL endpoint + API key | ✓ |

**User's choice:** Connectivity validator for `javstash_url` that validates the connection via API key. Title for the API key field: `"StashAPI 令牌"`.
**Notes:** User explicitly specified the Chinese title. Validator should test that the endpoint is reachable and the key is accepted.

---

## Stub Crawler Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Raise `NotImplementedError` | Clear signal that the crawler is registered but not functional | ✓ |
| Return empty `CrawlerResponse` | Silently succeed with no data | |
| Log "not yet implemented" | Warn but don't crash | |

**User's choice:** Raise `NotImplementedError`
**Notes:** User confirmed with "Yes" — the first and most explicit option.

---

## Agent's Discretion

- Position of `JAVSTASH` in priority lists (after `THEPORNDB` by convention)
- Exact placement of config fields in `models.py` (near `theporndb_api_token`)

## Deferred Ideas

None — discussion stayed within phase scope.
