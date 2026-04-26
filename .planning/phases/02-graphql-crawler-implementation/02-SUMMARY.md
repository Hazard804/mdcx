# Phase 2: GraphQL Crawler Implementation - Summary

**Date:** 2026-04-26
**Status:** ✅ Completed

## Accomplishments

- **GraphQL Transport**: Implemented `_post_graphql` helper in `StashGraphQLCrawler` using `self.async_client` and `ApiKey` header authorization.
- **Lookup Strategy**:
    - **Direct ID**: Extracts scene ID from `appoint_url` using regex (pattern: `/scenes/(\d+)`).
    - **Hash Lookup**: Implemented `oshash` computation with a safety guard; queries Stash using `findSceneByHash`.
    - **Number Fallback**: Implemented fallback to `findScenes` search by番号 if hash lookup fails or returns no results.
- **Data Mapping**:
    - Mapped GraphQL `Scene` fields to `CrawlerData`.
    - Implemented runtime conversion from seconds to minutes.
    - Added female-performer filtering for the `actors` field.
    - Attached `actor_photo` and `all_actor_photo` as dynamic attributes for compatibility with downstream consumers.

## Technical Details

- **File Modified**: `mdcx/crawlers/javstash.py`
- **Queries**: `FIND_BY_HASH_QUERY`, `FIND_BY_NUMBER_QUERY`, `FIND_BY_ID_QUERY`
- **Error Handling**: Missing API key or GraphQL errors raise `CralwerException` with user-friendly messages.

## Verification Results

- ✅ Missing API key triggers correct exception.
- ✅ URL parsing correctly extracts ID and calls `findScene`.
- ✅ Scene data mapping correctly handles performers, photos, and runtime.
- ✅ All internal tests passed using mocked GraphQL responses.
