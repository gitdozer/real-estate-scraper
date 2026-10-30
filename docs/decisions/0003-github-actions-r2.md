# 0003 — Run on GitHub Actions, store data on Cloudflare R2

Date: 2026-10-25 · Status: accepted

## Context
Constraints: no machine owned by the user, free services only (GitHub Actions, Google Cloud, Cloudflare), one daily run of 20–50 minutes, and data growing by ~2–3 GB per year.

## Decision
- **Collection runs on GitHub Actions**, with a daily cron plus manual triggering. The repository is **public at first** (unlimited minutes) so we can measure real usage; later it may become private if usage fits within the 2,000 free minutes per month.
- **Data lives on Cloudflare R2** (10 GB free, no download/egress fees), as Parquet files partitioned by date plus a state file.
- The code does not depend on Actions: it runs the same way on any machine that has the R2 environment variables.

## Alternatives considered
- **Google Cloud e2-micro VM** (always free): great for collection, but it means managing a server, and only 1 GB/month of outbound traffic is free. It remains **plan B** if the site blocks GitHub Actions.
- **Cloudflare Workers**: the free plan allows 50 outbound requests and 10 ms of CPU per invocation. Not suitable.
- **A SQLite database downloaded and re-uploaded on every run**: risk of corruption and uncontrolled growth. Parquet files appended per date are more robust and DuckDB can read them directly.

## Consequences
- Public repository ⇒ workflow logs are public: logs and the job summary contain only aggregate numbers, never listing data. The R2 secrets are not visible and are not passed to forks.
- GitHub disables cron schedules on public repositories after 60 days without commits: the `status` command (and, later, the dashboard) reports when data is stale.
- The GitHub Actions terms of service are about activity related to the repository's software: a scheduled scraping job is a grey area, but the risk is low for ~30 minutes a day. No code obfuscation (it would not reduce the risk).
