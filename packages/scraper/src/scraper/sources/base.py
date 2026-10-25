"""Interfaccia comune delle fonti. Una nuova fonte (es. sito di un'agenzia) implementa questi metodi."""

from typing import Protocol

from scraper.models import Detail, ListPage


class Source(Protocol):
    name: str
    page_size: int

    def list_url(self, city_slug: str, contract: str, page: int) -> str: ...

    def parse_list_page(self, html: str, city: str, contract: str, page: int) -> ListPage: ...

    def detail_url(self, path_or_id: str) -> str: ...

    def parse_detail_page(self, html: str, listing_id: str) -> Detail: ...

    def photo_url(self, photo_id: str) -> str: ...
