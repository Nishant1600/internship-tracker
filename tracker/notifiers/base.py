from abc import ABC, abstractmethod
from typing import Optional

from tracker.config import TelegramConfig
from tracker.models import Job


class Notifier(ABC):
    @abstractmethod
    async def send_digest(
        self,
        jobs: list[Job],
        resume_score: Optional[int],
        stats: dict,
    ) -> bool:
        ...
