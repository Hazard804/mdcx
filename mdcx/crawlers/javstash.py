"""JavStash GraphQL scraper — Phase 1 stub.

Full implementation in Phase 2. This skeleton registers the crawler
so it appears in the MDCx engine and can be assigned to website lists.
"""

from typing import TYPE_CHECKING, Any, override

import oshash

from ..config.manager import manager
from ..config.models import Website
from .base import BaseCrawler, Context, CralwerException, CrawlerData

if TYPE_CHECKING:
    from mdcx.web_async import AsyncWebClient


class StashGraphQLCrawler(BaseCrawler):
    """Stash-box GraphQL metadata scraper (javstash.org).

    Phase 1: registered but not functional — `_run` raises NotImplementedError.
    Phase 2: implemented GraphQL transport and extraction logic.
    """

    def __init__(self, client: "AsyncWebClient", base_url: str = "", browser=None):
        super().__init__(client, base_url, browser)
        self.api_key = manager.config.javstash_api_key

    async def _post_graphql(self, ctx: Context, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise CralwerException("请在设置中配置 StashAPI 令牌 (javstash_api_key)")

        headers = {
            "ApiKey": self.api_key,
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/graphql"
        json_data = {"query": query, "variables": variables}

        data, error = await self.async_client.post_json(url, json_data=json_data, headers=headers)

        if error:
            raise CralwerException(f"GraphQL 请求失败: {error}")

        if not data or "data" not in data:
            errors = data.get("errors") if data else None
            error_msg = errors[0].get("message") if errors else "未知错误"
            raise CralwerException(f"GraphQL 返回错误: {error_msg}")

        return data["data"]

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVSTASH

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://javstash.org"

    FIND_BY_HASH_QUERY = """
    query($checksum: String, $oshash: String) {
      findSceneByHash(input: {checksum: $checksum, oshash: $oshash}) {
        id
        title
        code
        details
        date
        urls
        studio { name }
        tags { name }
        performers {
          name
          gender
          image_path
        }
        files {
          duration
        }
        paths {
          screenshot
        }
      }
    }
    """

    FIND_BY_NUMBER_QUERY = """
    query($q: String!) {
      findScenes(filter: {q: $q, per_page: 5}) {
        scenes {
          id
          title
          code
          details
          date
          urls
          studio { name }
          tags { name }
          performers {
            name
            gender
            image_path
          }
          files {
            duration
          }
          paths {
            screenshot
          }
        }
      }
    }
    """

    FIND_BY_ID_QUERY = """
    query($id: ID!) {
      findScene(id: $id) {
        id
        title
        code
        details
        date
        urls
        studio { name }
        tags { name }
        performers {
          name
          gender
          image_path
        }
        files {
          duration
        }
        paths {
          screenshot
        }
      }
    }
    """

    @override
    async def _run(self, ctx: Context) -> CrawlerData:
        scene = None

        # 1. Direct ID lookup via appoint_url
        if ctx.input.appoint_url:
            import re

            match = re.search(r"/scenes/(\d+)", ctx.input.appoint_url)
            if match:
                scene_id = match.group(1)
                ctx.debug(f"通过 URL 解析到 ID: {scene_id}")
                data = await self._post_graphql(ctx, self.FIND_BY_ID_QUERY, {"id": scene_id})
                scene = data.get("findScene")

        # 2. Hash lookup
        if not scene and ctx.input.file_path:
            try:
                oshash_value = oshash.oshash(str(ctx.input.file_path))
                ctx.debug(f"计算 oshash: {oshash_value}")
                data = await self._post_graphql(
                    ctx, self.FIND_BY_HASH_QUERY, {"oshash": oshash_value, "checksum": None}
                )
                scene = data.get("findSceneByHash")
            except Exception as e:
                ctx.debug(f"⚠️ oshash 计算失败，跳过哈希搜索: {e}")

        # 3. Number fallback
        if not scene and ctx.input.number:
            ctx.debug(f"尝试按番号搜索: {ctx.input.number}")
            data = await self._post_graphql(ctx, self.FIND_BY_NUMBER_QUERY, {"q": ctx.input.number})
            scenes = data.get("findScenes", {}).get("scenes", [])
            if scenes:
                scene = scenes[0]

        if not scene:
            raise CralwerException("未找到匹配场景")

        return self._map_scene(scene, ctx)

    def _map_scene(self, scene: dict[str, Any], ctx: Context) -> CrawlerData:
        # Extract fields
        title = scene.get("title", "")
        details = scene.get("details", "")
        release = scene.get("date", "")
        year = release[:4] if release else ""
        studio = scene.get("studio", {}).get("name", "") if scene.get("studio") else ""
        tags = [t["name"] for t in scene.get("tags", [])]
        screenshot = scene.get("paths", {}).get("screenshot", "")

        # Duration to runtime (minutes)
        duration = None
        files = scene.get("files", [])
        if files and files[0].get("duration"):
            duration = files[0]["duration"]

        runtime = ""
        if duration:
            try:
                runtime = str(int(float(duration) / 60))
            except (ValueError, TypeError):
                pass

        # Performers
        performers = scene.get("performers", [])
        all_actors = [p["name"] for p in performers]
        actors = [p["name"] for p in performers if p.get("gender") != "MALE"]

        # Photos
        actor_photo = {p["name"]: p.get("image_path", "") for p in performers if p.get("gender") != "MALE"}
        all_actor_photo = {p["name"]: p.get("image_path", "") for p in performers}

        # Construct CrawlerData
        data = CrawlerData(
            title=title,
            originaltitle=title,
            outline=details,
            originalplot=details,
            release=release,
            year=year,
            studio=studio,
            publisher=studio,
            tags=tags,
            thumb=screenshot,
            poster=screenshot,
            runtime=runtime,
            number=scene.get("code") or ctx.input.number,
            actors=actors,
            all_actors=all_actors,
            external_id=str(scene.get("id")),
            image_download=False,
            image_cut="right",
            source=self.site().value,
        )

        # Attach dynamic attributes for v1 compat / downstream use
        # (The planner noted these are checked by the v1_compat layer or other consumers)
        data.actor_photo = actor_photo
        data.all_actor_photo = all_actor_photo

        return data

    # The following abstract methods are required by GenericBaseCrawler
    # but since _run is overridden, they will never be called.

    @override
    async def _generate_search_url(self, ctx: Context):
        raise NotImplementedError

    @override
    async def _parse_search_page(self, ctx: Context, html, search_url: str):
        raise NotImplementedError

    @override
    async def _parse_detail_page(self, ctx: Context, html, detail_url: str):
        raise NotImplementedError
