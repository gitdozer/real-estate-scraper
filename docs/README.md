# Documentation index

If you are coming back to the project after a while, read these in order:

1. [overview.md](overview.md) — what the project is, why it exists, and where it stands.
2. [architecture.md](architecture.md) — how the daily collection works.
3. [data-dictionary.md](data-dictionary.md) — every file and column we collect: meaning, type, origin.
4. [disappearance-logic.md](disappearance-logic.md) — how we decide whether a listing is new, changed, gone or has reappeared.
5. [runbook.md](runbook.md) — how to run the collection, restore the state, add a municipality, and what to do when something fails.

Further reading:

- [sources/trovacasa.md](sources/trovacasa.md) — structure of the trovacasa.it site, CSS selectors, measured limits.
- [decisions/](decisions) — decision log, with context and the alternatives we considered:
  - [0001 — trovacasa.it as the initial source](decisions/0001-trovacasa-as-source.md)
  - [0002 — casa.it excluded](decisions/0002-casa-it-excluded.md)
  - [0003 — GitHub Actions + Cloudflare R2](decisions/0003-github-actions-r2.md)
  - [0004 — Monorepo](decisions/0004-monorepo.md)
  - [0005 — Gone means sold, with separate dates](decisions/0005-gone-means-sold.md)
  - [0006 — Rate-limited requests to the site](decisions/0006-rate-limiting.md)
- [superpowers/specs/](superpowers/specs) — the approved design document.
- [superpowers/plans/](superpowers/plans) — implementation plans.
