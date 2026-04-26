---
wave: 1
depends_on: []
files_modified:
  - mdcx/crawlers/javstash.py
autonomous: true
---

# Phase 2: GraphQL Crawler Implementation - Plan

## Task 1: API Config Access and Graphql Transport
<task>
<read_first>
- mdcx/crawlers/javstash.py
- mdcx/crawlers/theporndb.py
- mdcx/crawlers/avbase_new.py
- mdcx/crawlers/base/types.py
</read_first>
<action>
Modify `mdcx/crawlers/javstash.py` to establish the API key, URL, and the GraphQL transport layer.
1. In `StashGraphQLCrawler`, add `__init__` that takes `client` and `base_url=None`, calls `super().__init__(client, base_url)`, and then sets `self.api_key = manager.config.javstash_api_key`. Add `from ..config.manager import manager` to the file imports.
2. Define a helper method `async def _post_graphql(self, ctx, query: str, variables: dict)`:
   - Check if `self.api_key` is truthy. If not, raise `CralwerException("请在设置中配置 StashAPI 令牌 (javstash_api_key)")`.
   - Set up headers: `{"ApiKey": self.api_key, "Content-Type": "application/json"}`
   - Use `manager.computed.async_client.post_json(f"{self.base_url}/graphql", json_data={"query": query, "variables": variables}, headers=headers)`
   - Extract `data` from the response JSON and return it. If the GraphQL response contains an `errors` key or HTTP error, raise `CralwerException` with the error details.
</action>
<acceptance_criteria>
- `javstash.py` imports `manager` from `..config.manager`
- `StashGraphQLCrawler.__init__` assigns `self.api_key = manager.config.javstash_api_key`
- `_post_graphql` sends POST requests to `{self.base_url}/graphql` with `ApiKey: {self.api_key}` header
- `_post_graphql` raises `CralwerException` with user-friendly text if API key is missing
</acceptance_criteria>
</task>

## Task 2: GraphQL Queries and Lookup Strategy
<task>
<read_first>
- mdcx/crawlers/javstash.py
- mdcx/crawlers/theporndb.py
</read_first>
<action>
Implement the scene lookup strategy in `mdcx/crawlers/javstash.py` by completely overriding `_run(self, ctx)`. 
1. Define class constants for the GraphQL queries:
   - `FIND_BY_HASH_QUERY = "query($checksum: String, $oshash: String) { findSceneByHash(input: {checksum: $checksum, oshash: $oshash}) { id title code details date urls studio { name } tags { name } performers { name gender image_path } files { duration } paths { screenshot } } }"`
   - `FIND_BY_NUMBER_QUERY = "query($q: String!) { findScenes(filter: {q: $q, per_page: 5}) { scenes { id title code details date urls studio { name } tags { name } performers { name gender image_path } files { duration } paths { screenshot } } } }"`
   - `FIND_BY_ID_QUERY = "query($id: ID!) { findScene(id: $id) { id title code details date urls studio { name } tags { name } performers { name gender image_path } files { duration } paths { screenshot } } }"`
2. Implement `_run(self, ctx)`:
   - If `ctx.input.appoint_url` is present, use a regex `re.search(r"/scenes/(\d+)", ctx.input.appoint_url)` to extract the ID. If found, query `FIND_BY_ID_QUERY` with `{"id": id}`.
   - If no direct URL, compute oshash: `oshash_value = oshash.oshash(str(ctx.input.file_path))` wrapped in a `try/except Exception as e:`. If it fails, log `ctx.debug(f"⚠️ oshash 计算失败，跳过哈希搜索: {e}")` and set `oshash_value = None`.
   - If `oshash_value` exists, query `FIND_BY_HASH_QUERY` with `{"oshash": oshash_value}`.
   - If hash returns null/empty, fallback to number: query `FIND_BY_NUMBER_QUERY` with `{"q": ctx.input.number}`. Take `data["findScenes"]["scenes"][0]` if list is not empty.
   - If no scene is found after all strategies, raise `CralwerException("未找到匹配场景")`.
</action>
<acceptance_criteria>
- `StashGraphQLCrawler` overrides `_run` and does not call `super()._run` or the `_generate_search_url` abstract methods
- `_run` correctly delegates to `FIND_BY_ID_QUERY` when `appoint_url` matches `/scenes/(\d+)`
- `_run` calls `oshash.oshash` on `ctx.input.file_path` inside a try/except block
- `_run` falls back to `FIND_BY_NUMBER_QUERY` if `FIND_BY_HASH_QUERY` fails or returns empty
- Raises `CralwerException` if no scene is found across all attempts
</acceptance_criteria>
</task>

## Task 3: Scene Data Mapping
<task>
<read_first>
- mdcx/crawlers/javstash.py
- mdcx/crawlers/theporndb.py
- mdcx/crawlers/base/types.py
</read_first>
<action>
Implement the data mapping logic in `mdcx/crawlers/javstash.py` inside `_run` to construct a `CrawlerResult` and populate legacy fields.
1. Extract fields from the GraphQL `scene` dict:
   - `title`: `scene.get("title", "")`
   - `originaltitle`: `scene.get("title", "")`
   - `outline`: `scene.get("details", "")`
   - `originalplot`: `scene.get("details", "")`
   - `release`: `scene.get("date", "")`
   - `year`: `release[:4]` if `release` else `""`
   - `studio`: `scene.get("studio", {}).get("name", "")` if `scene.get("studio")` else `""`
   - `publisher`: `studio`
   - `tags`: `[t["name"] for t in scene.get("tags", [])]`
   - `thumb` and `poster`: `scene.get("paths", {}).get("screenshot", "")`
   - `website`: `scene.get("urls", [""])[0]` if `scene.get("urls")` else `""`
   - `runtime`: Extract `duration` from `scene.get("files", [{}])[0].get("duration")`. Convert seconds (float/int) to minutes string: `str(int(float(duration) / 60))` if duration exists, else `""`.
   - `number`: `scene.get("code")` or `ctx.input.number`
2. Process performers and actor photos:
   - `all_actors` list: names of all performers.
   - `actors` list: names of performers where `gender != "MALE"`.
   - `actor_photo` dict: `{p["name"]: p.get("image_path", "") for p in performers if p.get("gender") != "MALE"}`
   - `all_actor_photo` dict: `{p["name"]: p.get("image_path", "") for p in performers}`
3. Instantiate `CrawlerData(number=..., title=..., ...)` with the mapped fields. Set `external_id=str(scene.get("id"))`. Set `image_download=False` and `image_cut="right"`.
4. Wrap `CrawlerData` in `CrawlerResponse` and return it. Wait, the `BaseCrawler` framework automatically handles `CrawlerResponse` inside `_run` if you yield or return `CrawlerData`, but for `actor_photo` legacy injection, we must hook it properly. Look at `base/base.py` `_run`. Return the `CrawlerData` object directly. To inject `actor_photo` and `all_actor_photo`, we need to attach them to `CrawlerData` directly even if not defined in dataclass, or set them up so the compat layer finds them. The `theporndb` crawler uses the legacy `main()` signature returning a huge dict. `StashGraphQLCrawler` inherits from `BaseCrawler` which returns `CrawlerData`. Update: add `actor_photo` and `all_actor_photo` as dynamic attributes on the `CrawlerData` object (`data.actor_photo = actor_photo`, `data.all_actor_photo = all_actor_photo`). The `v1_compat` layer checks for these attributes.
</action>
<acceptance_criteria>
- `runtime` is correctly calculated by dividing GraphQL `duration` (seconds) by 60 and converted to a string
- Female performers are correctly filtered into `actors` by skipping `gender == "MALE"`
- `data.actor_photo` and `data.all_actor_photo` are dynamically attached to the returned `CrawlerData` object as dictionaries mapping name to URL
- `CrawlerData` object is successfully returned from `_run` containing the mapped `title`, `outline`, `studio`, `thumb`, `poster`, and `tags`
</acceptance_criteria>
</task>

## Verification
1. Run a crawler test passing `Website.JAVSTASH` and `manager.config.javstash_api_key = ""` to verify `CralwerException` is raised with the correct message.
2. Provide a mock `appoint_url` like `https://javstash.org/scenes/12345` and assert the crawler correctly parses `12345` and executes the `FIND_BY_ID_QUERY`.
3. Provide a file path without an oshash match and verify the system correctly falls back to executing the `FIND_BY_NUMBER_QUERY`.
4. Validate that the returned `CrawlerData` has the dynamically attached `actor_photo` dictionary and `runtime` in minutes format.

## Requirements Addressed
- SCN-01..03
- DAT-01..03
- PER-01..03
- TRN-01..02
