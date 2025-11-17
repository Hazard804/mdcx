import asyncio
from collections.abc import Awaitable, Coroutine
from typing import Any


class GatherGroup[T = Any]:
    """
    类似 asyncio.TaskGroup 的 API, 但底层使用 asyncio.gather 实现, 因此可在部分任务抛出异常时继续运行.

    始终将异常作为结果返回, 调用方需手动检查. 如果需要直接抛出异常, 可使用 TaskGroup.
    """

    def __init__(self, timeout: float | None = None):
        self._tasks: list[Coroutine] = []
        self._results: list[Any]
        self._entered = False
        self._timeout = timeout

    def add(self, coro: Coroutine[Any, Any, T]) -> Awaitable[T]:
        """
        创建一个任务并添加到组中.

        Args:
            coro: 要执行的协程或可等待对象

        Returns:
            创建的 Task 对象
        """
        if not self._entered:
            raise RuntimeError("create_task() 只能在 async with 语句内部调用")

        self._tasks.append(coro)
        return coro

    async def __aenter__(self) -> "GatherGroup[T]":
        self._entered = True
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if not self._tasks:
            return

        # 支持组级别的超时控制（可选）
        try:
            if self._timeout is not None:
                self._results = await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True), timeout=self._timeout
                )
            else:
                # 使用原有的 gather 等待所有任务完成
                self._results = await asyncio.gather(*self._tasks, return_exceptions=True)
        except TimeoutError:
            # 超时时，asyncio.wait_for 会自动取消内部的 gather 任务
            # 我们只需要创建超时异常结果，不需要手动取消 Coroutine
            timeout_error = TimeoutError(f"GatherGroup 整体超时 ({self._timeout}s)")
            self._results = [timeout_error] * len(self._tasks)

    @property
    def results(self) -> list[T | Exception]:
        """
        获取所有任务的结果, 只有在上下文管理器退出后才可用.
        """
        return self._results


if __name__ == "__main__":

    async def task(i: int):
        await asyncio.sleep(i)
        if i == 2:
            raise ValueError(f"Error in task {i}")
        print(f"Task {i} completed")
        return f"Result of task {i}"

    async def main():
        async with GatherGroup[str]() as group:
            group.add(task(1))
            group.add(task(3))
            group.add(task(2))
        r = group.results
        print("All tasks completed with results:", r)

    asyncio.run(main())
