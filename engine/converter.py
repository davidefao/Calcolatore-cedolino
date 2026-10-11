"""Motore di conversione: report del provider -> righe del tracciato VOCI.

Due fasi, volutamente separate:

1. prepara(): legge ogni riga del report, la riconcilia (dipendente, voce),
   la valida e la etichetta (anche come "fuori periodo"). Nessuna scelta
   dell'utente è necessaria qui.
2. genera(): somma per coppia dipendente/voce e produce le righe a 38
   caratteri, in base alla scelta dell'utente sulle righe fuori periodo.

Così il sito può rielaborare il risultato quando l'utente cambia scelta
senza rileggere il file.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field

from engine.formatter import formatta_record
from engine.parsing import (ErroreDato, data_a_periodo, importo_a_centesimi,
                            periodo_a_testo, valida_periodo)
from engine.reader import TabellaLetta
from engine.riconciliazione import Anagrafica, CatalogoVoci, ErroreRiconciliazione

TERMINATORE_RIGA = "\r\n"   # come nel file di esempio fornito (CRLF, anche dopo l'ultima riga)


class ErroreConfigurazione(Exception):
    """La configurazione del provider è incompleta o non coerente."""


# ================================================================ dati

@dataclass
class Movimento:
    riga: int
    dipendente: str          # codice gestionale
    etichetta: str           # nome leggibile, per i messaggi
    voce: str
    importo_cent: int
    fuori_periodo: bool = False
    motivo_fuori: str = ""   # es. "data 2026-08-28 (agosto 2026)" o "data non leggibile"
    data_testo: str = ""


@dataclass
class Scarto:
    riga: int | None
    chi: str
    motivo: str


@dataclass
class Preparazione:
    righe_lette: int = 0
    movimenti: list = field(default_factory=list)
    scarti: list = field(default_factory=list)
    avvisi: list = field(default_factory=list)

    @property
    def fuori_periodo(self) -> list:
        return [m for m in self.movimenti if m.fuori_periodo]

    @property
    def negativi(self) -> list:
        """Righe con importo negativo (storni): il sito le mostra prima del download."""
        return [m for m in self.movimenti if m.importo_cent < 0]


@dataclass
class Risultato:
    righe_output: list           # righe a 38 caratteri, già ordinate
    totale_cent: int
    scarti: list
    avvisi: list
    movimenti_inclusi: int
    movimenti_esclusi: int       # esclusi perché fuori periodo su scelta dell'utente

    def testo_output(self) -> str:
        return "".join(r + TERMINATORE_RIGA for r in self.righe_output)


# ================================================================ configurazione

def carica_config(percorso_o_testo) -> dict:
    """Legge una configurazione da file (Path/str di percorso) o da testo JSON."""
    testo = str(percorso_o_testo)
    if not testo.lstrip().startswith("{"):
        with open(testo, encoding="utf-8") as f:
            testo = f.read()
    try:
        config = json.loads(testo)
    except json.JSONDecodeError as e:
        raise ErroreConfigurazione(f"Configurazione non valida (JSON): {e}") from e
    valida_config(config)
    return config


def valida_config(c: dict) -> None:
    mancanti = [k for k in ("nome", "file", "data", "importo", "dipendente", "trattamento")
                if k not in c]
    if mancanti:
        raise ErroreConfigurazione(f"Nella configurazione mancano: {', '.join(mancanti)}")
    for sezione, chiavi in (("data", ("colonna", "formato")),
                            ("importo", ("colonna",)),
                            ("dipendente", ("tipo", "colonne")),
                            ("trattamento", ("colonne",))):
        for k in chiavi:
            if k not in c[sezione]:
                raise ErroreConfigurazione(f"In «{sezione}» manca «{k}»")


# ================================================================ fase 1

def _val(riga, colonna: str) -> str:
    if colonna not in riga.valori:
        raise ErroreConfigurazione(
            f"La colonna «{colonna}» non esiste nel file. "
            f"Colonne trovate: {', '.join(riga.valori)}"
        )
    return riga.valori[colonna].strip()


def prepara(tabella: TabellaLetta, config: dict, ditta: int, periodo: str,
            anagrafica: Anagrafica, catalogo: CatalogoVoci) -> Preparazione:
    valida_config(config)
    periodo = valida_periodo(periodo)
    periodo_num = int(periodo)

    cfg_imp, cfg_dip = config["importo"], config["dipendente"]
    cfg_tr, cfg_data = config["trattamento"], config["data"]
    prep = Preparazione(righe_lette=len(tabella.righe))
    avvisi_visti = set()

    for r in tabella.righe:
        etichetta = " ".join(
            _val(r, c) for c in cfg_dip.get("etichetta", cfg_dip["colonne"]) if _val(r, c)
        ) or "(senza nome)"

        try:
            cent = importo_a_centesimi(
                _val(r, cfg_imp["colonna"]),
                cfg_imp.get("decimale", ","), cfg_imp.get("migliaia", ""))
            dip = anagrafica.trova(
                cfg_dip["tipo"],
                " ".join(_val(r, c) for c in cfg_dip["colonne"]),
                str(int(ditta)))
            trattamento = " ".join(
                v for v in (_val(r, c) for c in cfg_tr["colonne"]) if v)
            sotto = _val(r, cfg_tr["sottocategoria"]) if cfg_tr.get("sottocategoria") else ""
            voce, avviso = catalogo.trova(trattamento, sotto, cfg_tr.get("eccezioni", []))
        except (ErroreDato, ErroreRiconciliazione) as e:
            prep.scarti.append(Scarto(r.numero, etichetta, str(e)))
            continue

        if avviso and avviso not in avvisi_visti:
            avvisi_visti.add(avviso)
            prep.avvisi.append(avviso)

        data_testo = _val(r, cfg_data["colonna"])
        fuori, motivo = False, ""
        try:
            if data_a_periodo(data_testo, cfg_data["formato"]) != periodo_num:
                fuori = True
                mese = data_a_periodo(data_testo, cfg_data["formato"])
                motivo = f"data {data_testo} ({periodo_a_testo(str(mese))})"
        except ErroreDato:
            fuori, motivo = True, f"data non leggibile («{data_testo}»)" if data_testo else "data mancante"

        prep.movimenti.append(Movimento(
            riga=r.numero, dipendente=dip.codice, etichetta=etichetta, voce=voce,
            importo_cent=cent, fuori_periodo=fuori, motivo_fuori=motivo,
            data_testo=data_testo))
    return prep


# ================================================================ fase 2

def _ordine(codice: str):
    """Numerico se possibile (4 prima di 10), poi testuale."""
    return (0, int(codice), "") if codice.isdigit() else (1, 0, codice)


def genera(prep: Preparazione, ditta: int, periodo: str,
           includi_fuori_periodo: bool = True) -> Risultato:
    periodo = valida_periodo(periodo)
    somme = defaultdict(int)
    inclusi = esclusi = 0

    for m in prep.movimenti:
        if m.fuori_periodo and not includi_fuori_periodo:
            esclusi += 1
            continue
        somme[(m.dipendente, m.voce)] += m.importo_cent
        inclusi += 1

    scarti = list(prep.scarti)
    avvisi = list(prep.avvisi)
    righe, totale = [], 0

    for (dip, voce) in sorted(somme, key=lambda k: (_ordine(k[0]), _ordine(k[1]))):
        cent = somme[(dip, voce)]
        if cent == 0:
            avvisi.append(f"Dipendente {dip}, voce {voce}: importi che si annullano (totale 0,00), "
                          "nessun record generato")
            continue
        if cent < 0:
            scarti.append(Scarto(None, f"dipendente {dip}, voce {voce}", (
                f"totale negativo ({cent / 100:.2f} €): il tracciato non ammette importi "
                "negativi, record non generato".replace(".", ","))))
            continue
        try:
            righe.append(formatta_record(ditta, dip, voce, cent, periodo))
        except ValueError as e:
            scarti.append(Scarto(None, f"dipendente {dip}, voce {voce}",
                                 f"record non generabile: {e}"))
            continue
        totale += cent

    return Risultato(righe_output=righe, totale_cent=totale, scarti=scarti,
                     avvisi=avvisi, movimenti_inclusi=inclusi, movimenti_esclusi=esclusi)
