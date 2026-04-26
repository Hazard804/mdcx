---
phase: 1
plan: 1.2
title: "Crawler Skeleton & Registration"
wave: 2
depends_on: [1.1]
files_modified:
  - mdcx/crawlers/javstash.py
  - mdcx/crawlers/__init__.py
requirements: [REG-01, REG-02]
autonomous: true
---

# Plan 1.2 — Crawler Skeleton & Registration

<objective>
Create `mdcx/crawlers/javstash.py` with a stub `StashGraphQLCrawler` class that inherits from `BaseCrawler`, and register it in `mdcx/crawlers/__init__.py` using `register_crawler()`.
</objective>

<must_haves>
## Goal-Backward Verification

<truths>
- StashGraphQLCrawler.site() returns Website.JAVSTASH (REG-01)
- StashGraphQLCrawler is registered via register_crawler() in __init__.py (REG-02)
- StashGraphQLCrawler._run() raises NotImplementedError (D-06)
- StashGraphQLCrawler.base_url_() returns "https://javstash.org" (matches config default)
- The crawler class inherits from BaseCrawler (not GenericBaseCrawler directly — follows MissavCrawler pattern)
</truths>
</must_haves>

---

## Task 1: Create `mdcx/crawlers/javstash.py`

<read_first>
- mdcx/crawlers/base/base.py (full file — BaseCrawler class, GenericBaseCrawler, site(), base_url_(), _run())
- mdcx/crawlers/missav.py (lines 260-320 — MissavCrawler class header as reference for minimal new-style crawler)
- mdcx/config/enums.py (Website enum — confirm JAVSTASH exists after Plan 1.1)
</read_first>

<action>
Create `mdcx/crawlers/javstash.py` with the following content:

```python
"""JavStash GraphQL scraper — Phase 1 stub.

Full implementation in Phase 2. This skeleton registers the crawler
so it appears in the MDCx engine and can be assigned to website lists.
"""

from typing import override

from ..config.models import Website
from .base import BaseCrawler, CrawlerData


class StashGraphQLCrawler(BaseCrawler):
    """Stash-box GraphQL metadata scraper (javstash.org).

    Phase 1: registered but not functional — `_run` raises NotImplementedError.
    Phase 2 will implement the GraphQL transport and extraction logic.
    """

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVSTASH

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://javstash.org"

    @override
    async def _run(self, ctx):
        raise NotImplementedError(
            "StashGraphQLCrawler is not yet implemented. "
            "Phase 2 will add GraphQL transport and data extraction."
        )

    # The following abstract methods are required by GenericBaseCrawler
    # but since _run is overridden to raise, they will never be called.

    @override
    async def _generate_search_url(self, ctx):
        raise NotImplementedError

    @override
    async def _parse_search_page(self, ctx, html, search_url):
        raise NotImplementedError

    @override
    async def _parse_detail_page(self, ctx, html, detail_url):
        raise NotImplementedError
```
</action>

<acceptance_criteria>
- File `mdcx/crawlers/javstash.py` exists
- `grep "class StashGraphQLCrawler" mdcx/crawlers/javstash.py` returns exactly 1 match
- `grep "Website.JAVSTASH" mdcx/crawlers/javstash.py` returns at least 1 match
- `grep "NotImplementedError" mdcx/crawlers/javstash.py` returns at least 1 match for `_run`
- `grep "base_url_" mdcx/crawlers/javstash.py` returns a line with `"https://javstash.org"`
- `grep "BaseCrawler" mdcx/crawlers/javstash.py` returns lines showing inheritance
</acceptance_criteria>

---

## Task 2: Register `StashGraphQLCrawler` in `__init__.py`

<read_first>
- mdcx/crawlers/__init__.py (full file — import structure and register_crawler calls at lines 90-93)
</read_first>

<action>
In `mdcx/crawlers/__init__.py`, make two changes:

**1. Add import** — after line 48 (`from .javdb_new import JavdbCrawler`), add:
```python
from .javstash import StashGraphQLCrawler
```

**2. Add registration** — after line 93 (`register_crawler(missav.MissavCrawler)`), add:
```python
register_crawler(StashGraphQLCrawler)
```

The registration block should look like:
```python
register_crawler(DmmCrawler)
register_crawler(JavdbCrawler)
register_crawler(AvbaseCrawler)
register_crawler(missav.MissavCrawler)
register_crawler(StashGraphQLCrawler)
```
</action>

<acceptance_criteria>
- `grep "from .javstash import StashGraphQLCrawler" mdcx/crawlers/__init__.py` returns exactly 1 match
- `grep "register_crawler(StashGraphQLCrawler)" mdcx/crawlers/__init__.py` returns exactly 1 match
- The import line appears in the import section (before line 50)
- The register_crawler call appears after `register_crawler(missav.MissavCrawler)`
</acceptance_criteria>

---

<verification>
## Verification Criteria

1. `python -c "from mdcx.crawlers.javstash import StashGraphQLCrawler; assert StashGraphQLCrawler.site().value == 'javstash'"` exits 0
2. `python -c "from mdcx.crawlers.javstash import StashGraphQLCrawler; assert StashGraphQLCrawler.base_url_() == 'https://javstash.org'"` exits 0
3. `python -c "from mdcx.crawlers import get_crawler; from mdcx.config.enums import Website; c = get_crawler(Website.JAVSTASH); assert c is not None; assert c.__name__ == 'StashGraphQLCrawler'"` exits 0
4. `python -c "
from mdcx.crawlers.javstash import StashGraphQLCrawler
import asyncio
async def test():
    from mdcx.models.types import CrawlerInput
    c = StashGraphQLCrawler(client=None)
    try:
        await c._run(c.new_context(CrawlerInput(number='test')))
        assert False, 'should have raised'
    except NotImplementedError:
        pass
asyncio.run(test())
"` exits 0
</verification>
