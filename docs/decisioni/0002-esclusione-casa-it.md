# 0002 — Esclusione di casa.it

Data: 2026-10-25 · Stato: accettata

## Contesto
casa.it era un candidato come aggregatore molto completo. Alla prima richiesta (2026-10-25) risponde **403** con header `X-DataDome: protected`: è protetto da DataDome, un servizio anti-bot professionale (impronta TLS, impronta del browser, comportamento, reputazione dell'IP).

## Decisione
casa.it è **escluso**. Non si tenta di aggirare la protezione.

## Alternative scartate
- **Aggirare DataDome** (proxy residenziali, browser "stealth", servizi di risoluzione captcha): costa decine di euro al mese (fuori dal vincolo "solo gratuito"), è fragile (si rompe a ogni aggiornamento di DataDome), aggira una protezione esplicita del sito e indebolisce la posizione rispetto al diritto sui generis sulle banche dati.

## Conseguenze
- Il guadagno perso è probabilmente piccolo: le agenzie pubblicano lo stesso immobile su più portali.
- La copertura si allargherà con siti di agenzie non protetti (fase 4).
