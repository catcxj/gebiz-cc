from __future__ import annotations

from .base import BaseScraper
from ..config import settings


def get_scraper() -> BaseScraper:
    if settings.use_mock_scraper:
        from .mock import MockGeBIZScraper
        return MockGeBIZScraper()
    from .gebiz import GeBIZScraper
    return GeBIZScraper()
