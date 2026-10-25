from datetime import date

import polars as pl
import pytest

from scraper.storage import (
    LocalStorage,
    R2Storage,
    partition_key,
    prune_partitions,
    read_parquet,
    scraper_version,
    write_parquet,
)


def test_parquet_roundtrip_adds_version_columns(tmp_path):
    s = LocalStorage(tmp_path)
    df = pl.DataFrame({"listing_id": ["1", "2"], "price_eur": [100, None], "tags": [["a"], []]})
    write_parquet(s, "observations/dt=2026-10-26/part-0.parquet", df, "0.1.0+test")
    back = read_parquet(s, "observations/dt=2026-10-26/part-0.parquet")
    assert back["listing_id"].to_list() == ["1", "2"] and back["tags"].to_list() == [["a"], []]
    assert back["schema_version"].to_list() == [1, 1]
    assert back["scraper_version"].unique().to_list() == ["0.1.0+test"]


def test_read_missing_returns_none(tmp_path):
    assert read_parquet(LocalStorage(tmp_path), "state/listings.parquet") is None
    assert LocalStorage(tmp_path).read_bytes("nope") is None


def test_list_and_delete(tmp_path):
    s = LocalStorage(tmp_path)
    s.write_bytes("raw/dt=2026-01-01/a.parquet", b"x")
    s.write_bytes("raw/dt=2026-01-02/a.parquet", b"y")
    s.write_bytes("state/listings.parquet", b"z")
    assert s.list_keys("raw/") == ["raw/dt=2026-01-01/a.parquet", "raw/dt=2026-01-02/a.parquet"]
    s.delete("raw/dt=2026-01-01/a.parquet")
    assert s.list_keys("raw/") == ["raw/dt=2026-01-02/a.parquet"]


def test_partition_key():
    assert partition_key("observations", date(2026, 10, 26)) == "observations/dt=2026-10-26/part-0.parquet"
    assert partition_key("raw", date(2026, 10, 26), "raw.parquet") == "raw/dt=2026-10-26/raw.parquet"


def test_prune_partitions_keeps_recent(tmp_path):
    s = LocalStorage(tmp_path)
    run = date(2026, 10, 26)
    s.write_bytes(partition_key("raw", date(2026, 7, 18)), b"old")  # 100 giorni prima
    s.write_bytes(partition_key("raw", date(2026, 10, 16)), b"new")  # 10 giorni prima
    assert prune_partitions(s, "raw", keep_days=90, run_date=run) == 1
    assert s.list_keys("raw/") == [partition_key("raw", date(2026, 10, 16))]


def test_scraper_version_uses_github_sha(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "abcdef123456")
    assert scraper_version().endswith("+abcdef1")
    monkeypatch.delenv("GITHUB_SHA")
    assert scraper_version().endswith("+local")


def test_r2_from_env_requires_variables(monkeypatch):
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="R2_ACCOUNT_ID"):
        R2Storage.from_env()


def test_r2_from_env_builds_endpoint(monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", "acc123")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "s")
    monkeypatch.setenv("R2_BUCKET", "annunci")
    r2 = R2Storage.from_env()
    assert r2.bucket == "annunci" and r2.endpoint == "https://acc123.r2.cloudflarestorage.com"
