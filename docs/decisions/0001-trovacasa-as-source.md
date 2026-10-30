# 0001 — trovacasa.it as the initial source

Date: 2026-10-25 · Status: accepted

## Context
We need the residential listings (sale and rent) of 8 municipalities, every day, with as much detail as possible, without getting blocked and without bypassing any protection. immobiliare.it and idealista are ruled out from the start because they block scraping.

## Decision
We start with **trovacasa.it**. Reconnaissance on 2026-10-25 found:
- no anti-bot protection (IIS/ASP.NET server) and a permissive robots.txt;
- ~38,000 listings across the chosen municipalities, with complete pagination (24 per page);
- 0 blocks over 710 requests at up to 31 requests/s (at 16 connections the server starts to slow down);
- the detail page exposes coordinates, the agency's internal reference, the description and the features; the listing cards on the search-result pages expose the full list of photos.

## Alternatives considered
- **casa.it** — protected by DataDome (see [0002](0002-casa-it-excluded.md)).
- **Picking the "most complete" aggregator on paper** — unnecessary: casa.it is excluded anyway and trovacasa has good coverage. Agency websites will be evaluated in Phase 4 by measuring how much extra coverage they add.

## Consequences
- trovacasa.it is owned by Immobiliare.it S.p.A., so it could add protections in the future. The run flags an abnormal drop in listings (> 5%), and the completeness checks prevent false disappearances.
- The code has a "source" abstraction so that other sites can be added without touching the rest.
- The site's intermittent 500 errors (redirects to `/Error/InternalServerError`) require automatic retries.
