from abc import ABC, abstractmethod
from typing import AsyncIterator

from tracker.config import ScraperConfig
from tracker.models import RawJob


class BaseScraper(ABC):
    def __init__(self, company: str, url: str, config: ScraperConfig) -> None:
        self.company = company
        self.url = url
        self.config = config

    @abstractmethod
    async def fetch(self) -> AsyncIterator[RawJob]:
        ...
