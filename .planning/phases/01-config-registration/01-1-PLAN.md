---
phase: 1
plan: 1.1
title: "Config Fields & Priority Lists"
wave: 1
depends_on: []
files_modified:
  - mdcx/config/enums.py
  - mdcx/config/models.py
  - mdcx/config/v1.py
  - resources/config/default_config.json
requirements: [CFG-01, CFG-02, CFG-03]
autonomous: true
---

# Plan 1.1 — Config Fields & Priority Lists

<objective>
Add `Website.JAVSTASH` enum, `javstash_url` + `javstash_api_key` config fields, V1 migration defaults, default_config.json entries, and insert `Website.JAVSTASH` into all relevant `site_prority` lists in both Pydantic defaults and the JSON config.
</objective>

<must_haves>
## Goal-Backward Verification

<truths>
- Website.JAVSTASH must exist in enums.py as `JAVSTASH = "javstash"` (D-01 prerequisite)
- javstash_api_key field must have title "StashAPI 令牌" (D-03, user-specified exact string)
- javstash_url defaults to "https://javstash.org" (D-05)
- javstash_api_key defaults to "" (D-05)
- JAVSTASH appears after THEPORNDB in all site_prority lists (D-02)
- V1 ConfigV1 dataclass has javstash_api_key and javstash_url fields with correct defaults (backward compat)
</truths>
</must_haves>

---

## Task 1: Add `Website.JAVSTASH` to enums.py

<read_first>
- mdcx/config/enums.py (lines 489-531 — the Website enum)
</read_first>

<action>
In `mdcx/config/enums.py`, add `JAVSTASH = "javstash"` to the `Website` enum.

Insert it alphabetically after `IQQTV` (line 509) and before `JAV321` (line 510):

```python
    IQQTV = "iqqtv"
    JAV321 = "jav321"
```
becomes:
```python
    IQQTV = "iqqtv"
    JAVSTASH = "javstash"
    JAV321 = "jav321"
```
</action>

<acceptance_criteria>
- `grep -n "JAVSTASH" mdcx/config/enums.py` returns a line containing `JAVSTASH = "javstash"`
- Line is between IQQTV and JAV321 in alphabetical order
</acceptance_criteria>

---

## Task 2: Add config fields to models.py

<read_first>
- mdcx/config/models.py (lines 621-632 — Network Settings region, specifically theporndb_api_token pattern)
</read_first>

<action>
In `mdcx/config/models.py`, in the `# region: Network Settings` block, after line 628 (`theporndb_api_token`), add two new fields:

```python
    javstash_api_key: str = Field(default="", title="StashAPI 令牌")
    javstash_url: str = Field(default="https://javstash.org", title="StashAPI 地址")
```

Insert these immediately after the `theporndb_api_token` line (628) and before the `javdb` line (629).
</action>

<acceptance_criteria>
- `grep -n "javstash_api_key" mdcx/config/models.py` returns a line containing `Field(default="", title="StashAPI 令牌")`
- `grep -n "javstash_url" mdcx/config/models.py` returns a line containing `Field(default="https://javstash.org"`
- Both fields appear between `theporndb_api_token` and `javdb` lines
</acceptance_criteria>

---

## Task 3: Add `Website.JAVSTASH` to site_prority lists in models.py

<read_first>
- mdcx/config/models.py (lines 385-447 — field_configs default_factory with all FieldConfig entries)
- .planning/phases/01-config-registration/01-CONTEXT.md (D-01 decision — which fields get JAVSTASH)
</read_first>

<action>
In `mdcx/config/models.py`, in the `field_configs` default_factory dict (lines 385-447), add `Website.JAVSTASH` after `Website.THEPORNDB` in the `site_prority` lists for these `CrawlerResultFields`:

1. `TITLE` (line 388): `[Website.THEPORNDB, Website.JAVSTASH, Website.OFFICIAL, ...]`
2. `ORIGINALTITLE` (line 392): `[Website.THEPORNDB, Website.JAVSTASH, Website.OFFICIAL, ...]`
3. `OUTLINE` (line 395): `[Website.THEPORNDB, Website.JAVSTASH, Website.OFFICIAL, ...]`
4. `ORIGINALPLOT` (line 399): `[Website.THEPORNDB, Website.JAVSTASH, Website.OFFICIAL, ...]`
5. `ACTORS` (line 402): `[Website.THEPORNDB, Website.JAVSTASH, Website.OFFICIAL, ...]`
6. `ALL_ACTORS` (line 406): `[Website.THEPORNDB, Website.JAVSTASH, Website.JAVDB, ...]`
7. `TAGS` (line 410): `[Website.THEPORNDB, Website.JAVSTASH, Website.OFFICIAL, ...]`
8. `STUDIO` (line 422): `[Website.THEPORNDB, Website.JAVSTASH, Website.OFFICIAL, ...]`
9. `PUBLISHER` (line 426): `[Website.THEPORNDB, Website.JAVSTASH, Website.OFFICIAL, ...]`
10. `THUMB` (line 429): `[Website.THEPORNDB, Website.JAVSTASH, Website.DMM, ...]`
11. `POSTER` (line 430): `[Website.THEPORNDB, Website.JAVSTASH, Website.DMM, ...]`
12. `RELEASE` (line 436): `[Website.THEPORNDB, Website.JAVSTASH, Website.OFFICIAL, ...]`
13. `RUNTIME` (line 439): `[Website.THEPORNDB, Website.JAVSTASH, Website.OFFICIAL, ...]`

Do NOT add to: `DIRECTORS` (no director data from GraphQL), `SERIES` (no series data), `SCORE` (no score data), `WANTED` (no wanted data), `EXTRAFANART` (no extrafanart data), `TRAILER` (no trailer data).
</action>

<acceptance_criteria>
- `grep -c "Website.JAVSTASH" mdcx/config/models.py` returns 13 (exactly 13 occurrences in site_prority lists)
- Each occurrence of `Website.JAVSTASH` in a site_prority list appears immediately after `Website.THEPORNDB`
- Fields DIRECTORS, SERIES, SCORE, WANTED, EXTRAFANART, TRAILER do NOT contain Website.JAVSTASH
</acceptance_criteria>

---

## Task 4: Add V1 migration defaults to v1.py

<read_first>
- mdcx/config/v1.py (lines 276-286 — proxy section with theporndb_api_token)
</read_first>

<action>
In `mdcx/config/v1.py`, in the `ConfigV1` dataclass, after line 281 (`theporndb_api_token: str = r""`), add:

```python
    javstash_api_key: str = r""
    javstash_url: str = r"https://javstash.org"
```
</action>

<acceptance_criteria>
- `grep -n "javstash_api_key" mdcx/config/v1.py` returns a line containing `javstash_api_key: str = r""`
- `grep -n "javstash_url" mdcx/config/v1.py` returns a line containing `javstash_url: str = r"https://javstash.org"`
- Both lines appear after `theporndb_api_token` and before `# Cookies`
</acceptance_criteria>

---

## Task 5: Add entries to default_config.json

<read_first>
- resources/config/default_config.json (lines 749-757 — proxy/network area with theporndb_api_token)
</read_first>

<action>
In `resources/config/default_config.json`, after line 755 (`"theporndb_api_token": ""`), add:

```json
  "javstash_api_key": "",
  "javstash_url": "https://javstash.org",
```

Also update ALL `site_prority` arrays in the `field_configs` section to include `"javstash"` after `"theporndb"` for the same 13 fields listed in Task 3. Specifically, add `"javstash"` after the `"theporndb"` entry in these field_configs keys:
- title, originaltitle, outline, originalplot, actors, all_actors, tags, studio, publisher, thumb, poster, release, runtime

Do NOT add to: directors, series, score, wanted, extrafanart, trailer.
</action>

<acceptance_criteria>
- `grep -c "javstash" resources/config/default_config.json` returns at least 15 (2 config fields + 13 site_prority entries)
- `grep "javstash_api_key" resources/config/default_config.json` returns `"javstash_api_key": ""`
- `grep "javstash_url" resources/config/default_config.json` returns `"javstash_url": "https://javstash.org"`
- Each "javstash" in a site_prority array appears immediately after "theporndb"
</acceptance_criteria>

---

## Task 6: Add URL connectivity validator to models.py

<read_first>
- mdcx/config/models.py (lines 3-10 — imports, especially field_validator)
- mdcx/config/models.py (lines 107-108 — Config class definition)
</read_first>

<action>
In `mdcx/config/models.py`, add a Pydantic `field_validator` for `javstash_url` in the `Config` class. This validator should:
1. Strip whitespace and trailing slashes
2. If both `javstash_url` and `javstash_api_key` are set (non-empty), attempt an HTTP GET to `{javstash_url}/graphql` with header `ApiKey: {javstash_api_key}` to verify connectivity
3. If the connection fails, log a warning but do NOT raise an error (config should still load)
4. If `javstash_api_key` is empty, skip connectivity check

Add after the `model_post_init` of `TranslateConfig` (line 91) or at the end of the Config class before the deprecated region. Use `@field_validator('javstash_url', mode='after')` with `@classmethod`.

**Note:** Since Pydantic validators don't have access to other fields easily in v2 `field_validator`, use `model_validator(mode='after')` instead, which gives access to the full model instance:

```python
    from pydantic import model_validator

    @model_validator(mode="after")
    def _validate_javstash_connection(self) -> "Config":
        url = (self.javstash_url or "").strip().rstrip("/")
        if url:
            self.javstash_url = url
        api_key = self.javstash_api_key
        if url and api_key:
            try:
                import urllib.request
                req = urllib.request.Request(
                    f"{url}/graphql",
                    data=b'{"query":"{__typename}"}',
                    headers={"ApiKey": api_key, "Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                import logging
                logging.getLogger(__name__).warning("StashAPI 连接验证失败: %s", url)
        return self
```

Add this method inside the `Config` class, after the `update` staticmethod (around line 799) and before the `_convert_field_configs` staticmethod.
</action>

<acceptance_criteria>
- `grep -n "_validate_javstash_connection" mdcx/config/models.py` returns exactly 1 line
- `grep -n "model_validator" mdcx/config/models.py` returns at least 1 line
- The validator accesses `self.javstash_url` and `self.javstash_api_key`
- The validator does NOT raise on connection failure — only logs a warning
</acceptance_criteria>

---

<verification>
## Verification Criteria

1. `python -c "from mdcx.config.enums import Website; assert Website.JAVSTASH.value == 'javstash'"` exits 0
2. `python -c "from mdcx.config.models import Config; c = Config(); assert c.javstash_api_key == ''; assert c.javstash_url == 'https://javstash.org'"` exits 0
3. `python -c "from mdcx.config.models import Config, Website; c = Config(); assert Website.JAVSTASH in c.field_configs['title'].site_prority"` exits 0
4. `python -c "from mdcx.config.v1 import ConfigV1; c = ConfigV1(); assert c.javstash_api_key == ''; assert c.javstash_url == 'https://javstash.org'"` exits 0
5. `python -c "import json; d = json.load(open('resources/config/default_config.json')); assert d['javstash_api_key'] == ''"` exits 0
</verification>
