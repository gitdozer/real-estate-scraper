# Panoramica

## Perché esiste

L'obiettivo finale è stimare, date le caratteristiche di un immobile:

- **il prezzo** a cui un agente immobiliare lo metterebbe in vendita (o in affitto);
- **il tempo di vendita**, cioè quanto resta online prima di sparire.

Per farlo servono dati storici che nessuno fornisce gratis. Questo progetto li costruisce raccogliendo **ogni giorno** gli annunci residenziali di alcuni comuni. La storia non si recupera a posteriori: ogni giorno senza raccolta è perso.

Progetto personale, nel tempo libero, solo strumenti gratuiti.

## Perimetro

- **Comuni:** Milano, Busto Arsizio, Gallarate, Monza, Legnano, Gorla Minore, Marnate, Castellanza (configurabili in `config/cities.yaml`).
- **Contratti:** vendita e affitto, tenuti separati.
- **Tipologie:** solo residenziale. Esclusi aste, interi stabili/palazzi, stanze e posti letto, box, commerciale, terreni. Nuove costruzioni, affitto con riscatto e immobili "a reddito" sono inclusi ma marcati.
- **Fonte:** trovacasa.it (vedi [decisioni/0001](decisioni/0001-fonte-trovacasa.md)).
- **Definizione di venduto:** l'annuncio sparisce dal sito (vedi [decisioni/0005](decisioni/0005-sparito-uguale-venduto.md)).

## Fasi

| Fase | Contenuto | Stato |
|---|---|---|
| 1 | Raccolta giornaliera automatica (GitHub Actions → Cloudflare R2), storico per annuncio, segnali per riconoscere ripubblicazioni (riferimento agenzia, coordinate, impronte foto, descrizione) | codice pronto (0.1.0), in attesa di messa in produzione |
| 2 | Riconoscimento di ripubblicazioni e duplicati: entità "immobile" che raggruppa più annunci | da fare |
| 3 | Dashboard locale (Streamlit + DuckDB) | da fare |
| 4 | Altre fonti (siti di reti di agenzie senza protezioni anti-bot) | da fare |
| 5 | Modelli: prezzo e tempo di vendita (analisi di sopravvivenza), arricchimento con quotazioni OMI | da fare |

## Dati storici

L'unico storico precedente è un'istantanea degli annunci di Milano in vendita del 2026-10-17 (17.304 annunci) raccolta da un vecchio scraper. Viene importata come punto di partenza (vedi `docs/runbook.md`).
