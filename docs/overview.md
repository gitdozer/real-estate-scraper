# Overview

## Why this project exists

The end goal is to estimate, given the features of a property:

- **the price** at which a real-estate agent would list it for sale (or for rent);
- **the time to sell**, i.e. how long the listing stays online before it disappears.

That requires historical data that nobody provides for free. This project builds it by collecting the residential listings of a handful of municipalities **every day**. History cannot be recovered after the fact: every day without a collection is lost for good.

It is a personal, spare-time project that uses only free tools.

## Scope

- **Municipalities:** Milano, Busto Arsizio, Gallarate, Monza, Legnano, Gorla Minore, Marnate, Castellanza (configurable in `config/cities.yaml`).
- **Contracts:** sale and rent, kept separate.
- **Property types:** residential only. Excluded: auctions, entire buildings, rooms and beds, garages, commercial property, land. New builds, rent-to-buy and income-producing properties ("a reddito") are included but flagged.
- **Source:** trovacasa.it (see [decisions/0001](decisions/0001-trovacasa-as-source.md)).
- **Definition of sold:** the listing disappears from the site (see [decisions/0005](decisions/0005-gone-means-sold.md)).

## Phases

| Phase | Content | Status |
|---|---|---|
| 1 | Automatic daily collection (GitHub Actions → Cloudflare R2), per-listing history, signals for recognizing re-posted listings (agency reference, coordinates, photo fingerprints, description) | code ready (0.1.0), awaiting production rollout |
| 2 | Recognizing re-posts and duplicates: a "property" entity that groups several listings | to do |
| 3 | Local dashboard (Streamlit + DuckDB) | to do |
| 4 | More sources (agency-network sites without anti-bot protection) | to do |
| 5 | Models: price and time to sell (survival analysis), enriched with OMI price quotations | to do |

## Historical data

The only earlier data is a snapshot of Milano listings for sale taken on 2026-10-17 (17,304 listings) by an old scraper. It is imported as the starting point (see `docs/runbook.md`).
