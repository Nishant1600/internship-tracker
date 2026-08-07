from abc import ABC, abstractmethod

from tracker.models import Job


class Notifier(ABC):
    @abstractmethod
    async def send_digest(
        self,
        jobs: list[Job],
        stats: dict,
    ) -> bool:
        ...
