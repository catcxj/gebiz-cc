from __future__ import annotations

from .base import BaseScraper
from ..config import settings


def get_scraper() -> BaseScraper:
    if settings.use_mock_scraper:
        from .mock import MockGeBIZScraper
        return MockGeBIZScraper()
    from .gebiz import GeBIZScraper
    return GeBIZScraper()


def get_scrapers() -> list[BaseScraper]:
    if settings.use_mock_scraper:
        from .mock import MockGeBIZScraper
        return [MockGeBIZScraper()]
    from .gebiz import GeBIZScraper
    from .psa import PSAScraper
    return [GeBIZScraper(), PSAScraper()]


def get_scraper_for_opp(opp) -> BaseScraper:
    if settings.use_mock_scraper:
        from .mock import MockGeBIZScraper
        return MockGeBIZScraper()
    agency = (opp.agency or "").upper()
    if "PSA" in agency:
        from .psa import PSAScraper
        return PSAScraper()
    from .gebiz import GeBIZScraper
    return GeBIZScraper()
