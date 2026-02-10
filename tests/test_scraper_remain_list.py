from pathlib import Path
from types import SimpleNamespace

import pytest

from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags


@pytest.mark.asyncio
async def test_run_uses_copied_remain_list(monkeypatch: pytest.MonkeyPatch):
    from mdcx.core import scraper as scraper_module

    Flags.reset()
    movie_list = [Path("MIAA-001.mp4"), Path("MIAA-002.mp4"), Path("MIAA-003.mp4"), Path("MIAA-004.mp4")]
    origin_first = movie_list[0]

    async def fake_run_tasks_with_limit(_self, scheduled_list: list[Path], _task_count: int, _thread_number: int):
        assert scheduled_list is movie_list
        assert Flags.remain_list is not scheduled_list

        Flags.remain_list.remove(origin_first)

        assert len(scheduled_list) == 4
        assert scheduled_list[0] == origin_first

    async def fake_save_success_list(_old_path=None, _new_path=None):
        return None

    async def fake_clean_empty_folders(_path: Path, _file_mode: FileMode):
        return None

    def fake_get_movie_path_setting(_file_path=None):
        return SimpleNamespace(movie_path=Path("."), ignore_dirs=[], softlink_path=Path("."))

    monkeypatch.setattr(scraper_module.Scraper, "_run_tasks_with_limit", fake_run_tasks_with_limit)
    monkeypatch.setattr(scraper_module, "save_success_list", fake_save_success_list)
    monkeypatch.setattr(scraper_module, "_clean_empty_fodlers", fake_clean_empty_folders)
    monkeypatch.setattr(scraper_module, "get_movie_path_setting", fake_get_movie_path_setting)
    monkeypatch.setattr(scraper_module.manager.config, "thread_number", 4)
    monkeypatch.setattr(scraper_module.manager.config, "thread_time", 0)
    monkeypatch.setattr(scraper_module.manager.config, "main_mode", 1)
    monkeypatch.setattr(scraper_module.manager.config, "switch_on", [])
    monkeypatch.setattr(scraper_module.manager.config, "scrape_softlink_path", False)
    monkeypatch.setattr(scraper_module.manager.config, "emby_on", [])
    monkeypatch.setattr(scraper_module.manager.config, "actor_photo_kodi_auto", False)

    scraper = scraper_module.Scraper(crawler_provider=object())
    await scraper._run(FileMode.Default, movie_list)

    assert movie_list == [Path("MIAA-001.mp4"), Path("MIAA-002.mp4"), Path("MIAA-003.mp4"), Path("MIAA-004.mp4")]
    assert Flags.remain_list == [Path("MIAA-002.mp4"), Path("MIAA-003.mp4"), Path("MIAA-004.mp4")]
