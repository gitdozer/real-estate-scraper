# 0004 — A single monorepo

Date: 2026-10-25 · Status: accepted

## Context
The project will contain a scraper, a dashboard, models and documentation. We considered keeping the project's version history in one repository and running the scraper from another, possibly on a second GitHub account.

## Decision
**One repository** on one account: a `uv` workspace with one package per component under `packages/` (`scraper`, `dashboard`, `models`), each with its own dependencies (so GitHub Actions installs only the scraper).

Versioning:
- the `main` branch always works; work happens on short-lived branches;
- Conventional Commits with a scope;
- SemVer versions **per component**, with tags `scraper-vX.Y.Z`, `dashboard-vX.Y.Z`, `models-vX.Y.Z`, and a `CHANGELOG.md` per component;
- **the version is stored inside the data**: every Parquet file carries `schema_version` and `scraper_version` (version + commit).

## Alternatives considered
- **Two repositories / two accounts**: the data schema written by the scraper and the one read by the dashboard and models would drift apart without anyone noticing; maintenance would be doubled; and GitHub's Terms of Service allow only one free account per person (apart from "machine accounts" used for automation).

## Consequences
- If the code ever needs to be private, the whole repository is made private (after checking how many Actions minutes it uses).
