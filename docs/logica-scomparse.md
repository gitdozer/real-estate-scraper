# Logica di comparsa, cambiamento e scomparsa

Codice: `packages/scraper/src/scraper/state.py` (funzione pura `reconcile`). Decisione di fondo: [decisioni/0005](decisioni/0005-sparito-uguale-venduto.md) — **un annuncio sparito si considera venduto**.

Il rischio numero uno del progetto sono le **scomparse false**: un errore di rete, una pagina mancante o una raccolta parziale registrati come "annuncio sparito". Per questo un annuncio cambia stato solo con prove certe.

## Stati

```
            (compare)                 assente + dettaglio 404/410
   ┌──────► active ──────────────────────────────────────────► removed
   │          │                                                  ▲
   │          │ assente + dettaglio 200 per 2 controlli          │ dettaglio 404/410
   │          ▼                                                  │ (ricontrollo settimanale)
   │       delisted ─────────────────────────────────────────────┘
   │          │
   └──────────┘  ricompare negli elenchi (da delisted o removed) → evento "reappeared"
```

- **active** — compare negli elenchi (o è assente da troppo poco per decidere).
- **delisted** — assente dagli elenchi (in raccolte complete) con la pagina di dettaglio che risponde ancora 200 in **2 controlli**, senza ricomparire nel frattempo. **Conta come scomparso** per il tempo di vendita.
- **removed** — la pagina di dettaglio risponde 404 (o 410).

## Le tre date

| Campo | Significato |
|---|---|
| `list_last_seen` | ultimo giorno in cui l'annuncio compariva negli elenchi. **È la data di fine per il tempo di vendita.** |
| `delisted_date` | primo giorno di assenza **con esito certo del controllo** (inizio dell'assenza poi confermata) |
| `detail_gone_date` | primo giorno in cui la pagina di dettaglio ha risposto 404/410 |

Tra `list_last_seen` e `delisted_date` può esserci più di un giorno (run saltato, segmento incompleto, controllo in errore): la scomparsa è avvenuta in quell'intervallo.

## Periodi online (spell)

Un annuncio può sparire e ricomparire con lo **stesso ID**. Ogni permanenza continuativa online è un *periodo* (spell) che inizia in `spell_start` e finisce in `list_last_seen`:

- per un annuncio nuovo `spell_start = first_seen`;
- quando ricompare, il periodo precedente si chiude (le sue date restano nell'evento `reappeared`: `spell_start`, `list_last_seen`, `delisted_date`) e se ne apre uno nuovo con `spell_start` = giorno della ricomparsa;
- gli eventi `removed` e `delisted` riportano le date del periodo che si chiude.

**La tabella `events` filtrata su `removed`/`delisted` è quindi direttamente l'elenco delle "vendite"**, ognuna con inizio e fine.

**Tempo di vendita** = `list_last_seen − spell_start` del periodo chiuso. Gli annunci con `first_seen_censored = true` erano già online al primo giorno di raccolta del loro segmento: il loro inizio reale è precedente (dato censurato a sinistra). Quelli ancora `active` sono censurati a destra. Va usata l'analisi di sopravvivenza.

## Regole di un run

Per ogni annuncio **presente** negli elenchi di oggi:
- se è nuovo → `active`, `first_seen = oggi`, evento `new`;
- se era `delisted` o `removed` → torna `active`, evento `reappeared` con le date del periodo precedente, e inizia un nuovo periodo;
- se il prezzo è diverso dall'ultimo → evento `price_change` (anche da/verso "nessun prezzo");
- in ogni caso `list_last_seen = oggi`, l'assenza si azzera.

Per ogni annuncio **assente**:
1. Se il suo segmento (fonte, comune, contratto) **non è stato raccolto** oggi o è stato raccolto **in modo incompleto** → nessuna modifica.
2. Altrimenti conta l'esito del controllo della pagina di dettaglio:
   - **404/410** → `removed` (evento `removed`; da `delisted` → evento `detail_gone`);
   - **200** → assenza +1; al secondo controllo con esito 200 senza ricomparsa nel frattempo → `delisted` (evento `delisted`). I giorni con esito incerto in mezzo non azzerano il conteggio;
   - **errore, timeout o controllo non eseguito** → nessuna modifica.

Il flag `data-eliminato` delle schede viene solo salvato: il suo significato va verificato confrontandolo con i 404 reali.

## Segmento completo (blocco di sicurezza)

Codice: `quality.py`. Un segmento (fonte, comune, contratto) è **completo** solo se:

1. la pagina 1 riporta il totale dichiarato dal sito (altrimenti motivo `no_declared_total`);
2. nessuna pagina elenco è fallita dopo tutti i tentativi (`failed_pages`);
3. gli annunci unici raccolti sono almeno il **97%** del totale dichiarato; per i segmenti con meno di **50** annunci dichiarati si ammettono al massimo **2** mancanti (`incomplete`).
4. gli annunci raccolti non sono calati in modo sospetto rispetto agli annunci attivi del segmento prima del run: il calo ammesso è il 5% (minimo 2 annunci) (`suspicious_drop`). Protegge dal caso in cui il sito dichiari per errore un totale sbagliato (es. "0 case"): il totale e gli annunci arrivano dalla stessa pagina, quindi da soli non bastano.
5. il run non è limitato con `--max-pages` (`max_pages`).

Un segmento incompleto **non genera scomparse** quel giorno e fa terminare il run con errore (email di GitHub). Per questo un run di prova con `--max-pages` non può mai registrare scomparse.

**Allarme calo:** se gli annunci attivi sono calati più del **5%** rispetto al run precedente, il run termina con errore anche se i segmenti risultano completi (segnale di un cambiamento del sito).

## Da verificare nei primi giorni

- Come il sito presenta un annuncio **realmente** rimosso (404? redirect? pagina con avviso?). Il 404 è stato verificato solo su ID inventati. Si salva l'HTML dei primi 50 controlli con esito 404 di ogni run (`raw/`).
- Il significato di `data-eliminato`.
- Annunci che cambiano segmento (es. stesso annuncio negli elenchi di due comuni vicini): lo stato ricorda l'ultimo segmento visto; se l'annuncio compare solo nell'altro segmento e quello non viene raccolto, potrebbe risultare `delisted`. Con la raccolta di tutti i comuni ogni giorno il caso non si presenta; da monitorare.
