"""Caricamento della configurazione: comuni (cities.yaml) e parametri (settings.yaml)."""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

Contract = Literal["vendita", "affitto"]


class City(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    istat: str
    slugs: dict[str, str]
    contracts: list[Contract]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_concurrency: int = 6
    image_concurrency: int = 8
    max_retries: int = 4
    timeout_s: float = 30.0
    error_window: int = 200
    error_threshold: float = 0.2
    rotation_days: int = 7
    photos_new: int = 6
    photos_backlog: int = 3
    max_photos_per_run: int = 30000
    completeness_min: float = 0.97
    small_segment_threshold: int = 50
    small_segment_max_missing: int = 2
    active_drop_alert: float = 0.05
    delisted_recheck_days: int = 7
    raw_retention_days: int = 90
    state_history_days: int = 30
    max_runtime_minutes: int = 100
    full_details: bool = False
    max_pages: int = 0


def load_cities(path: Path) -> list[City]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [City(**item) for item in data["cities"]]


def load_settings(path: Path, overrides: dict[str, Any]) -> Settings:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    data.update({k: v for k, v in overrides.items() if v is not None})
    return Settings(**data)
