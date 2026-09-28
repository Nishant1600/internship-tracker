import asyncio
import signal
from typing import Callable, Coroutine

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from tracker.config import ScheduleConfig


def create_scheduler(schedule_cfg: ScheduleConfig) -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone=schedule_cfg.timezone)


def schedule_cron(
    scheduler: AsyncIOScheduler,
    time_str: str,
    job_func: Callable[[], Coroutine],
) -> None:
    hour, minute = time_str.split(":")
    scheduler.add_job(
        job_func,
        trigger="cron",
        hour=int(hour),
        minute=int(minute),
    )


def schedule_daily_job(
    scheduler: AsyncIOScheduler,
    schedule_cfg: ScheduleConfig,
    job_func: Callable[[], Coroutine],
) -> None:
    schedule_cron(scheduler, schedule_cfg.time, job_func)


async def run_scheduler(
    schedule_cfg: ScheduleConfig,
    job_func: Callable[[], Coroutine],
    extra_jobs: list[tuple[str, Callable[[], Coroutine]]] | None = None,
) -> None:
    scheduler = create_scheduler(schedule_cfg)
    schedule_daily_job(scheduler, schedule_cfg, job_func)
    for time_str, func in extra_jobs or []:
        schedule_cron(scheduler, time_str, func)
    scheduler.start()

    stop_event = asyncio.Event()

    def _shutdown():
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    await stop_event.wait()
    scheduler.shutdown(wait=False)
