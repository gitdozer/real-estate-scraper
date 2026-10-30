# 0002 — casa.it excluded

Date: 2026-10-25 · Status: accepted

## Context
casa.it was a candidate because it is a very complete aggregator. On the very first request (2026-10-25) it answered **403** with the header `X-DataDome: protected`: it is protected by DataDome, a professional anti-bot service (TLS fingerprinting, browser fingerprinting, behavioral analysis, IP reputation).

## Decision
casa.it is **excluded**. We do not try to bypass the protection.

## Alternatives considered
- **Bypassing DataDome** (residential proxies, "stealth" browsers, captcha-solving services): it costs tens of euros a month (which breaks the "free tools only" constraint), it is fragile (it breaks with every DataDome update), it circumvents an explicit protection put in place by the site, and it weakens our position with respect to the sui generis database right.

## Consequences
- What we lose is probably small: agencies publish the same property on several portals.
- Coverage will be widened with unprotected agency websites (Phase 4).
