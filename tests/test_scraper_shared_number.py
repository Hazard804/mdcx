import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags
from mdcx.models.types import FileInfo


def _build_file_info(number: str) -> FileInfo:
    file_info = FileInfo.empty()
    file_info.number = number
    file_info.mosaic = "有码"
    file_info.file_path = Path(f"{number}.mp4")
    file_info.folder_path = Path(".")
    file_info.file_name = number
    file_info.file_ex = ".mp4"
    file_info.file_show_name = f"{number}.mp4"
    file_info.file_show_path = file_info.file_path
    file_info.sub_list = []
    return file_info


def _setup_scraper_test_env(monkeypatch: pytest.MonkeyPatch):
    from mdcx.core import scraper as scraper_module

    Flags.reset()

    async def fake_check_file(*_args, **_kwargs):
        return True

    def fake_get_movie_path_setting(_file_path=None):
        return SimpleNamespace(success_folder=Path("."), movie_path=Path("."))

    original_sleep = asyncio.sleep

    async def fast_sleep(_seconds: float):
        await original_sleep(0)

    monkeypatch.setattr(scraper_module, "check_file", fake_check_file)
    monkeypatch.setattr(scraper_module, "get_movie_path_setting", fake_get_movie_path_setting)
    monkeypatch.setattr(scraper_module.asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(scraper_module.manager.config, "main_mode", 1)
    monkeypatch.setattr(scraper_module.manager.config, "file_size", "0")
    return scraper_module


@pytest.mark.asyncio
async def test_same_number_waiting_task_stops_on_failed_status(monkeypatch: pytest.MonkeyPatch):
    scraper_module = _setup_scraper_test_env(monkeypatch)
    scraper = scraper_module.Scraper(crawler_provider=object())
    file_info = _build_file_info("ABC-123")

    Flags.json_get_status[file_info.number] = None

    task = asyncio.create_task(scraper._process_one_file(file_info, FileMode.Default))
    await asyncio.sleep(0.01)
    Flags.json_get_status[file_info.number] = False

    result = await asyncio.wait_for(task, timeout=1)
    assert result == (None, None)


@pytest.mark.asyncio
async def test_same_number_failed_status_returns_without_wait(monkeypatch: pytest.MonkeyPatch):
    scraper_module = _setup_scraper_test_env(monkeypatch)
    scraper = scraper_module.Scraper(crawler_provider=object())
    file_info = _build_file_info("DEF-456")

    Flags.json_get_status[file_info.number] = False

    result = await asyncio.wait_for(scraper._process_one_file(file_info, FileMode.Default), timeout=1)
    assert result == (None, None)
