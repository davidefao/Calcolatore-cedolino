# Analisi dei report dei provider

Documento di analisi (Fase 1): differenze tra i report, problemi trovati e regole decise per il motore di conversione.

## 1. Provider a confronto

| | **A** | **B** | **C** | **D** | **E** |
|---|---|---|---|---|---|
| Formato | xlsx | csv `;` | xls | csv `;` | xlsx |
| Righe di titolo | 3 righe, intestazione alla riga 4 | nessuna intestazione | intestazione alla riga 1 | intestazione alla riga 1 | intestazione alla riga 1 |
| Encoding | n/a | Windows-1252 | n/a | Windows-1252 | n/a |
| Chiave dipendente | Codice fiscale | Cognome + nome (nessun CF) | Matricola (`00000020`, con zeri) | Nome + cognome del dipendente | Codice dipendente |
| Importo | `151,00` (testo, virgola) | `3103,27` (virgola) | numero Excel (`312.1`) | `148,00` (virgola) | `€68.00` (euro, punto), colonna **Totale** |
| Trattamento fiscale | colonna *Tratt. Fiscale* | codice `X71180` | colonne *Art.* + *Rif. normativi* concatenate | colonna *Riferimento al TUIR* (+ *Tipologia di servizio* come sottocategoria) | colonna *Articolo* |
| Ditta nel kit | 4012 | 4027 | 4041 | 4093 | 4131 |

## 2. File di riconciliazione

**Lista_Dipendenti.csv**
- Contiene righe duplicate esatte: vanno eliminate.
- Lo stesso codice fiscale compare in ditte diverse, e lo stesso codice dipendente identifica persone diverse in ditte diverse. **La ricerca avviene sempre all'interno della ditta inserita in input.**

**Codici_Welfare_Voci_Payroll.csv**
- Separatore virgola, ma alcuni testi contengono virgole tra virgolette (`"Art.51 c. 2, f bis"`): si legge con un parser CSV, mai con `split(",")`.
- Righe ripetute e trattamenti con più codici distinti da una **sottocategoria** (es. `Art. 51 c.2 lett. f-bis` → 373 Istruzione non universitaria, 375 Centri estivi, 376 Assistenza familiari anziani).

## 3. Particolarità per provider

- **A**: `Benefit art.51 c.2 let d-bis` non esiste identico nei codici; si risolve col match normalizzato (→ 377).
- **B**: il primo campo (`19`) non è la ditta del gestionale. Il codice `X71133` non è nei codici. Il dipendente `MARINI SOFIA` non è in lista.
- **C**: file `.xls` reale (serve `xlrd`). Matricola da `00000020` a `20`. Importi float: convertire passando da stringa. Il trattamento è dato da due colonne.
- **D**: il codice fiscale nel file è quello del *fruitore* del benefit (spesso un familiare), quindi il dipendente si identifica solo per nome e cognome. `Matteo Martini` non è in lista.
- **E**: importi dalla colonna **Totale** (importo unitario × quantità). `Guerra Paolo` (codice 15052) non è presente nella ditta 4131.

## 4. Regole decise

### 4.1 Mappatura del trattamento sulla voce

1. Cerco il trattamento nel file dei codici, prima con il testo esatto, poi con il testo normalizzato (senza "Benefit", "lett/let", punti, spazi, maiuscole).
2. Se ci sono più righe, uso la sottocategoria indicata nel report, se esiste.
3. Se la sottocategoria non esiste nei codici, uso il **caso base** (la riga senza sottocategoria).
4. Se non c'è il caso base, la riga va in **errore** e finisce nel log degli scarti.

**Eccezioni dichiarate nella configurazione del provider** (non nel codice):
- Provider D: `Art. 51 c.2 lett. f-bis` con sottocategoria "Asilo nido" → **373**, perché i casi base disponibili nei codici sono discordanti (372 e 373) e il motore non può sceglierne uno da solo.
- Provider C: `Art.51 c. 3` con segno "Effettivo" → 194 (sottocategoria presente nei codici); con segno "Figurativo" → 371 (caso base).
- Provider E: `Art 100 [Iva 22%]` → 370 per match normalizzato, segnalato come **match approssimato** nell'esito.

### 4.2 Dipendente non trovato

Se il dipendente non è presente nella lista della ditta indicata, la riga viene scartata con messaggio esplicito (riga, nome, ditta, motivo). Esempio: *Alessia Fumagalli* (CF `FMGLSS92S52G273A`) non è nella lista della ditta 4012, pur comparendo nell'esempio di output come dipendente 25. Scelta consapevole: non si inventano codici.

### 4.3 Avviso prima del download

Se ci sono scarti o errori, **prima di scaricare il file l'utente vede un avviso in evidenza** con il numero di righe scartate e il motivo di ciascuna, e un log scaricabile. Il download resta possibile, ma solo dopo aver preso visione dell'avviso.

### 4.4 Altre regole tecniche

- Importi sempre in **centesimi interi** (mai float).
- Codici dipendente e voce sempre come **stringhe**; ordinamento finale numerico per dipendente, poi per voce.
- Un record per coppia dipendente/voce, con importi sommati.
- Output ASCII a 38 caratteri per riga, senza intestazione.

## 5. Verifica sul Provider A

Con ditta 4012 e periodo 202609, il Provider A produce 18 dei 19 record dell'esempio. L'unico mancante è quello di Fumagalli (dipendente 25), scartato per la regola 4.2.
