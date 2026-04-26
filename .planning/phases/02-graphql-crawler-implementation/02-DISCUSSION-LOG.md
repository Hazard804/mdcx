# Phase 2: GraphQL Crawler Implementation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-26
**Phase:** 2-GraphQL Crawler Implementation
**Areas discussed:** Config access pattern, appoint_url parsing, Data mapping gaps, oshash failure guard

---

## Config access pattern

| Option | Description | Selected |
|--------|-------------|----------|
| Inline Access | `from ..config.manager import manager` and read `manager.config` on every request. | |
| Construction Time | Read config once in `__init__` and store as `self.api_key`. | ✓ |

**User's choice:** read them once at construction time
**Notes:** N/A

---

## appoint_url parsing

| Option | Description | Selected |
|--------|-------------|----------|
| Regex | Use regex to extract the scene ID from the URL path. | |
| Review Stash | Review Stash source code (`D:\Dev\projects\stash`) to understand URL patterns and GraphQL schemas. | ✓ |

**User's choice:** please review the source codes: D:\Dev\projects\stash to figure out the best way.
**Notes:** Reviewed Stash source code. Found that Stash URLs are `/scenes/{id}` and GraphQL `findSceneByHash` exists as an elegant alternative to `findScenes` for hash lookups.

---

## Data mapping gaps

| Option | Description | Selected |
|--------|-------------|----------|
| ThePornDB Pattern | Inject `actor_photo` and `all_actor_photo` as plain dicts into the legacy return dict to be picked up by the compat layer. | ✓ |
| Extend CrawlerData | Add `actor_photo` to `CrawlerData`. | |

**User's choice:** follow the same pattern as ThePornDB
**Notes:** N/A

---

## oshash failure guard

| Option | Description | Selected |
|--------|-------------|----------|
| Log Warning | Wrap in try/except, log a warning, and fall through to number search. | ✓ |
| Raise Exception | Abort the scraping process. | |

**User's choice:** log a warning
**Notes:** N/A

---

## the agent's Discretion

None

## Deferred Ideas

None
