# Logica di comparsa, cambiamento e scomparsa

Codice: `packages/scraper/src/scraper/state.py` (funzione pura `reconcile`). Decisione di fondo: [decisioni/0005](decisioni/0005-sparito-uguale-venduto.md) — **un annuncio sparito si considera venduto**.

Il rischio numero uno del progetto sono le **scomparse false**: un errore di rete, una pagina mancante o una raccolta parziale registrati come "annuncio sparito". Per questo un annuncio cambia stato solo con prove certe.

## Stati

```
            (compare)                 assente + dettaglio 404
   ┌──────► active ──────────────────────────────────────────► removed
   │          │                                                  ▲
   │          │ assente + dettaglio 200 per 2 run completi       │ dettaglio 404
   │          ▼                                                  │ (ricontrollo settimanale)
   │       delisted ─────────────────────────────────────────────┘
   │          │
   └──────────┘  ricompare negli elenchi (da delisted o removed) → evento "reappeared"
```

- **active** — compare negli elenchi (o è assente da troppo poco per decidere).
- **delisted** — non compare più negli elenchi da 2 run completi consecutivi, ma la pagina di dettaglio risponde ancora. **Conta come scomparso** per il tempo di vendita.
- **removed** — la pagina di dettaglio risponde 404.

## Le tre date

| Campo | Significato |
|---|---|
| `list_last_seen` | ultimo giorno in cui l'annuncio compariva negli elenchi. **È la data di fine per il tempo di vendita.** |
| `delisted_date` | primo giorno di assenza (inizio dell'assenza poi confermata) |
| `detail_gone_date` | primo giorno in cui la pagina di dettaglio ha risposto 404 |

Tra `list_last_seen` e `delisted_date` può esserci più di un giorno se il run è saltato: la scomparsa è avvenuta in quell'intervallo.

**Tempo di vendita** = `list_last_seen − first_seen` per gli annunci `delisted`/`removed`. Gli annunci con `first_seen_censored = true` erano già online al primo giorno di raccolta del loro segmento: il loro inizio reale è precedente (dato censurato a sinistra). Quelli ancora `active` sono censurati a destra. Va usata l'analisi di sopravvivenza.

## Regole di un run

Per ogni annuncio **presente** negli elenchi di oggi:
- se è nuovo → `active`, `first_seen = oggi`, evento `new`;
- se era `delisted` o `removed` → torna `active`, evento `reappeared` (le date di scomparsa precedenti restano negli eventi);
- se il prezzo è diverso dall'ultimo → evento `price_change` (anche da/verso "nessun prezzo");
- in ogni caso `list_last_seen = oggi`, l'assenza si azzera.

Per ogni annuncio **assente**:
1. Se il suo segmento (fonte, comune, contratto) **non è stato raccolto** oggi o è stato raccolto **in modo incompleto** → nessuna modifica.
2. Altrimenti conta l'esito del controllo della pagina di dettaglio:
   - **404** → `removed` (evento `removed`; da `delisted` → evento `detail_gone`);
   - **200** → assenza +1; alla seconda assenza consecutiva → `delisted` (evento `delisted`);
   - **errore, timeout o controllo non eseguito** → nessuna modifica.

Il flag `data-eliminato` delle schede viene solo salvato: il suo significato va verificato confrontandolo con i 404 reali.

## Segmento completo (blocco di sicurezza)

Un segmento è "completo" se nessuna pagina elenco è fallita dopo i tentativi e se gli annunci raccolti sono almeno il 97% del totale dichiarato dal sito (per i segmenti sotto 50 annunci: al massimo 2 mancanti). *(Regole dettagliate con i controlli di qualità.)*

## Da verificare nei primi giorni

- Come il sito presenta un annuncio **realmente** rimosso (404? redirect? pagina con avviso?). Il 404 è stato verificato solo su ID inventati. Si salva l'HTML dei primi 50 controlli con esito 404 di ogni run (`raw/`).
- Il significato di `data-eliminato`.
