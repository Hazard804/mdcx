# Project: MDCx — JavStash Scraper

> Milestone: M2 — Studio Enrichment & Refinement
> Last updated: 2026-04-26

## What This Is

A metadata scraper for [MDCx](https://github.com/Hazard804/mdcx) that fetches scene and performer data from **javstash.org** (a community-run Stash instance) via its **GraphQL API**.

## Core Value

**Users with access to javstash.org get richer, curator-verified scene and actress metadata.** The scraper supports hash-based exact matching, fallback search by code, and direct URL parsing.

## Current State

- ✅ **M1 Shipped (2026-04-26)**: Core GraphQL transport, scene lookup (hash/code/ID), and performer data extraction with photo mapping implemented and verified.

## Decisions

| Decision | Rationale | Status |
|----------|-----------|--------|
| Use GraphQL, not HTML scraping | javstash.org exposes `/graphql`; structured data is more reliable than HTML parsing | ✅ Decided |
| New-style `StashBaseCrawler` | subclass of `GenericBaseCrawler`; reuses async HTTP, error handling, debug logging | ✅ Decided |
| Hash-first, number fallback lookup | Hash (oshash via `findSceneByHash`) gives exact match; number search is the safety net | ✅ Decided |
| Store `javstash_api_key` + `javstash_url` in `Config` | Mirrors `theporndb_api_token` field | ✅ Decided |
| Scrape Scenes + Performers | Actress photo URLs come from the GraphQL `performers` field | ✅ Decided |

## Requirements

### Validated (M1)

- ✓ `JAVSTASH` entry in `Website` enum
- ✓ `javstash_api_key` + `javstash_url` fields in `Config` model
- ✓ `StashGraphQLCrawler` class implementing `GenericBaseCrawler`
- ✓ Hash lookup: query `findSceneByHash` with `oshash`
- ✓ Number lookup: query `findScenes` by title/number keyword
- ✓ Direct lookup: parse `/scenes/(\d+)` from `appoint_url`
- ✓ Performer photo extraction and female-only filtering
- ✓ Scraper registered in `mdcx/crawlers/__init__.py`
- ✓ Config fields visible in UI settings
- ✓ User-facing error message when API key is missing

### Active (M2 - Backlog)

- [ ] Studio scraper (`findStudios`) — add studio aliases and network hierarchy
- [ ] Refactor standalone tests into `pytest` suite in `tests/`
- [ ] Support for user-hosted private Stash instances beyond javstash.org
- [ ] Batch fingerprint submission flow

## Evolution

This document evolves at phase transitions and milestone boundaries.

---
*Last updated: 2026-04-26 after M1 completion*
