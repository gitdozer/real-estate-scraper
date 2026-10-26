"""Storage dei dati: cartella locale (sviluppo, test) o Cloudflare R2 (produzione).

Le chiavi sono percorsi con "/" (es. "observations/dt=2026-10-26/part-0.parquet"),
uguali in locale e su R2. Layout completo in docs/dizionario-dati.md.
"""

import io
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

import polars as pl

from scraper import __version__
from scraper.models import SCHEMA_VERSION

_R2_VARS = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
_PARTITION_DATE = re.compile(r"/dt=(\d{4}-\d{2}-\d{2})/")


class ConfigError(RuntimeError):
    """Configurazione mancante o sbagliata (es. variabili d'ambiente di R2). Il messaggio è sicuro da stampare."""


class Storage(Protocol):
    def read_bytes(self, key: str) -> bytes | None: ...

    def write_bytes(self, key: str, data: bytes) -> None: ...

    def list_keys(self, prefix: str) -> list[str]: ...

    def delete(self, key: str) -> None: ...


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root.joinpath(*key.split("/"))

    def read_bytes(self, key: str) -> bytes | None:
        p = self._path(key)
        return p.read_bytes() if p.is_file() else None

    def write_bytes(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)  # scrittura atomica: mai file a metà

    def list_keys(self, prefix: str) -> list[str]:
        if not self.root.exists():
            return []
        keys = (p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file() and not p.name.endswith(".tmp"))
        return sorted(k for k in keys if k.startswith(prefix))

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class R2Storage:
    """Bucket Cloudflare R2 tramite l'API compatibile S3."""

    def __init__(self, account_id: str, access_key_id: str, secret_access_key: str, bucket: str):
        import boto3

        self.bucket = bucket
        self.endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
        self._s3 = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    @classmethod
    def from_env(cls) -> "R2Storage":
        missing = [v for v in _R2_VARS if not os.environ.get(v)]
        if missing:
            raise ConfigError(f"Variabili d'ambiente mancanti per R2: {', '.join(missing)}")
        return cls(*(os.environ[v] for v in _R2_VARS))

    def read_bytes(self, key: str) -> bytes | None:
        try:
            obj = self._s3.get_object(Bucket=self.bucket, Key=key)
        except self._s3.exceptions.NoSuchKey:
            return None
        return obj["Body"].read()

    def write_bytes(self, key: str, data: bytes) -> None:
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=data)

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        for page in self._s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(o["Key"] for o in page.get("Contents", []))
        return sorted(keys)

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=key)


def scraper_version() -> str:
    sha = os.environ.get("GITHUB_SHA")
    return f"{__version__}+{sha[:7]}" if sha else f"{__version__}+local"


def partition_key(dataset: str, run_date: date, name: str = "part-0.parquet") -> str:
    return f"{dataset}/dt={run_date:%Y-%m-%d}/{name}"


def write_parquet(storage: Storage, key: str, df: pl.DataFrame, scraper_version: str) -> None:
    df = df.with_columns(
        pl.lit(SCHEMA_VERSION, dtype=pl.Int32).alias("schema_version"),
        pl.lit(scraper_version, dtype=pl.Utf8).alias("scraper_version"),
    )
    buf = io.BytesIO()
    df.write_parquet(buf, compression="zstd")
    storage.write_bytes(key, buf.getvalue())


def read_parquet(storage: Storage, key: str) -> pl.DataFrame | None:
    data = storage.read_bytes(key)
    return pl.read_parquet(io.BytesIO(data)) if data is not None else None


def prune_partitions(storage: Storage, dataset: str, keep_days: int, run_date: date) -> int:
    """Cancella le partizioni di `dataset` più vecchie di `keep_days` giorni. Restituisce i file cancellati."""
    cutoff = run_date - timedelta(days=keep_days)
    deleted = 0
    for key in storage.list_keys(f"{dataset}/"):
        m = _PARTITION_DATE.search("/" + key)
        if m and date.fromisoformat(m.group(1)) < cutoff:
            storage.delete(key)
            deleted += 1
    return deleted
