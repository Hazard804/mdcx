---
status: complete
phase: 02-graphql-crawler-implementation
source:
  - .planning/phases/02-graphql-crawler-implementation/02-SUMMARY.md
started: 2026-04-26T20:27:00Z
updated: 2026-04-26T20:34:00Z
---

## Current Test

[testing complete]

## Tests

### 1. GraphQL Transport Authorization
expected: Requests to the GraphQL endpoint include the `ApiKey` header with the configured value. Missing API key triggers a `CralwerException` with a clear instruction message.
result: pass
note: Verified by `test_javstash_missing_api_key` in `test_javstash_standalone.py`.

### 2. Direct ID Lookup via URL
expected: Providing a Stash scene URL (e.g., `https://javstash.org/scenes/12345`) correctly extracts the ID and fetches the specific scene data without falling back to search.
result: pass
note: Verified by `test_javstash_url_parsing` in `test_javstash_standalone.py`.

### 3. Oshash Match Lookup
expected: If a file path is provided and its `oshash` matches a record on Stash, the scene is identified immediately via `findSceneByHash`.
result: pass
note: Verified by transport logic tests.

### 4. Number Search Fallback
expected: If hash lookup fails or returns no results, the crawler performs a search using the record's number (code) and selects the first matching scene.
result: pass
note: Verified by search fallback logic.

### 5. Metadata Mapping Accuracy
expected: Mapped data includes accurate title, outline, release date, studio, tags, and posters. The `runtime` is correctly converted from seconds to minutes (as a string).
result: pass
note: Verified by `test_javstash_mapping` in `test_javstash_standalone.py`.

### 6. Female Performer Filtering
expected: The `actors` list contains only female performers (gender != 'MALE'), while `all_actors` contains everyone. Photos are correctly mapped into the dynamic `actor_photo` and `all_actor_photo` attributes.
result: pass
note: Verified by `test_javstash_mapping` in `test_javstash_standalone.py`.

## Summary

total: 6
passed: 6
issues: 0
pending: 0
skipped: 0

## Gaps

[none yet]
