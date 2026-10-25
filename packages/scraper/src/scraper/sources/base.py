"""Interfaccia comune delle fonti. Una nuova fonte (es. sito di un'agenzia) implementa questi metodi."""

from typing import Protocol

from scraper.models import ListPage


class Source(Protocol):
    name: str
    page_size: int

    def list_url(self, city_slug: str, contract: str, page: int) -> str: ...

    def parse_list_page(self, html: str, city: str, contract: str, page: int) -> ListPage: ...

    def photo_url(self, photo_id: str) -> str: ...
