# Rules for AI sessions on this repository

Read first: `docs/README.md`, then the spec `docs/superpowers/specs/2026-10-25-real-estate-scraper-design.md` and the plan in `docs/superpowers/plans/`.

## Mandatory

1. **Documentation always up to date.** Every change that alters behavior, collected data, schema or the way the tool runs updates the documentation in `docs/` **in the same commit**. Every new or changed column goes in `docs/data-dictionary.md`; every schema change bumps `SCHEMA_VERSION` and is recorded in the schema history. Every non-trivial decision becomes a record in `docs/decisions/`.
2. **Never listing data in GitHub logs or job summaries** (the repository is public): aggregate counts only. Error details go in the report on R2.
3. **No data in the repository**, except the HTML test fixtures. CSV, Parquet, `.docx` and credentials stay out (`.gitignore`).
4. **No code obfuscation**; code must be readable and commented where the logic is not obvious.
5. **Never bypass anti-bot protections** (proxies, IP rotation, captcha solving). If a source blocks us, it is dropped.
6. **False disappearances are risk number one.** Any change to `state.py`, `planner.py`, `quality.py` or the pipeline must have tests showing that network errors, missing pages or partial runs do not produce `removed`/`delisted` events.
7. **Everything is in English**: code, identifiers, comments, documentation, log and program messages, job summaries, commit messages, PR titles and descriptions, issues, reviews, branch names, tags, release notes. The only exception is the chat with the user, which stays in Italian.

## Conventions

- Tests before code (pytest). Command: `uv run pytest`.
- Conventional Commits with scope: `feat(scraper): …`, `fix(scraper): …`, `docs: …`, `ci: …`.
- Per-component versions with tags `scraper-vX.Y.Z`, `dashboard-vX.Y.Z`, `models-vX.Y.Z`; record them in `CHANGELOG.md`.
