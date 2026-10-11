"""Logica di servizio per il sito: tutto ciò che non è disegno della pagina.

Non importa Streamlit, così si può provare con pytest.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from engine.converter import (ErroreConfigurazione, Preparazione, Risultato,
                              carica_config, prepara)
from engine.parsing import ErroreDato, periodo_a_testo, valida_periodo
from engine.reader import leggi_file
from engine.riconciliazione import carica_anagrafica, carica_catalogo

RADICE = Path(__file__).resolve().parent.parent
CARTELLA_CONFIG = RADICE / "configs"
CARTELLA_RICONCILIAZIONE = RADICE / "data" / "riconciliazione"
FILE_DIPENDENTI = "Lista_Dipendenti.csv"
FILE_CODICI = "Codici_Welfare_Voci_Payroll.csv"


class ErroreInstallazione(Exception):
    """Manca qualcosa dell'applicazione (non è colpa del file dell'utente)."""


# ---------------------------------------------------------------- input

def elenca_provider(cartella: Path = CARTELLA_CONFIG) -> dict:
    """{nome del provider: percorso della config}, in ordine alfabetico."""
    trovati = {}
    for percorso in sorted(cartella.glob("*.json")):
        try:
            trovati[carica_config(percorso)["nome"]] = percorso
        except ErroreConfigurazione:
            continue                      # una config rotta non deve bloccare il sito
    return dict(sorted(trovati.items()))


def valida_ditta(testo: str) -> int:
    t = (testo or "").strip()
    if not t:
        raise ErroreDato("Inserisci il codice ditta.")
    if not t.isdigit():
        raise ErroreDato("Il codice ditta deve contenere solo cifre, ad esempio 4012.")
    if len(t) > 6:
        raise ErroreDato("Il codice ditta può avere al massimo 6 cifre.")
    if int(t) == 0:
        raise ErroreDato("Il codice ditta non può essere zero.")
    return int(t)


def periodo_predefinito(oggi: date | None = None) -> str:
    """Il mese precedente a oggi, in formato AAAAMM: di solito è il cedolino da elaborare."""
    oggi = oggi or date.today()
    anno, mese = (oggi.year, oggi.month - 1) if oggi.month > 1 else (oggi.year - 1, 12)
    return f"{anno}{mese:02d}"


def nome_file_output(ditta: int, periodo: str) -> str:
    return f"VOCI_{int(ditta)}_{periodo}.txt"


# ---------------------------------------------------------------- conversione

def converti_file(percorso_config: Path, contenuto: bytes, nome_file: str,
                  ditta: int, periodo: str,
                  cartella_riconciliazione: Path = CARTELLA_RICONCILIAZIONE) -> Preparazione:
    """Legge il report e lo prepara. Solleva errori con messaggi per l'utente."""
    periodo = valida_periodo(periodo)
    config = carica_config(percorso_config)

    try:
        dipendenti = (cartella_riconciliazione / FILE_DIPENDENTI).read_bytes()
        codici = (cartella_riconciliazione / FILE_CODICI).read_bytes()
    except FileNotFoundError as e:
        raise ErroreInstallazione(
            f"Manca il file di riconciliazione «{Path(e.filename).name}» "
            f"nella cartella {cartella_riconciliazione.name}."
        ) from e

    tabella = leggi_file(contenuto, nome_file, config["file"])
    return prepara(tabella, config, ditta, periodo,
                   carica_anagrafica(dipendenti, ditta), carica_catalogo(codici))


# ---------------------------------------------------------------- presentazione

def formatta_euro(centesimi: int) -> str:
    """123456 -> '1.234,56'; -5 -> '-0,05'."""
    segno = "-" if centesimi < 0 else ""
    euro, cent = divmod(abs(centesimi), 100)
    return f"{segno}{euro:,}".replace(",", ".") + f",{cent:02d}"


def tabella_scarti(risultato: Risultato) -> list:
    return [{"Riga nel file": s.riga if s.riga else "—",
             "Dipendente": s.chi,
             "Motivo": s.motivo} for s in risultato.scarti]


def tabella_movimenti(movimenti: list, con_motivo: bool = False) -> list:
    righe = []
    for m in movimenti:
        r = {"Riga nel file": m.riga, "Dipendente": m.etichetta, "Voce": m.voce,
             "Importo (€)": formatta_euro(m.importo_cent)}
        if con_motivo:
            r["Perché"] = m.motivo_fuori
        righe.append(r)
    return righe


def conta_cose_da_controllare(prep: Preparazione, risultato: Risultato) -> int:
    return (len(risultato.scarti) > 0) + (len(prep.negativi) > 0) + (len(prep.fuori_periodo) > 0)


def log_anomalie(nome_provider: str, ditta: int, periodo: str, prep: Preparazione,
              risultato: Risultato, includi_fuori_periodo: bool | None) -> str:
    """Log delle anomalie, scaricabile dall'utente (testo semplice)."""
    righe = [
        f"LOG DELLA CONVERSIONE - {nome_provider} - ditta {ditta} - periodo {periodo} "
        f"({periodo_a_testo(periodo)})",
        f"Righe lette: {prep.righe_lette} | Record nel file: {len(risultato.righe_output)} | "
        f"Totale importi: {formatta_euro(risultato.totale_cent)} EUR",
        "",
    ]

    def sezione(titolo, voci):
        righe.append(f"== {titolo} ({len(voci)}) ==")
        righe.extend(voci if voci else ["nessuno"])
        righe.append("")

    sezione("RIGHE SCARTATE (non presenti nel file)", [
        f"riga {s.riga if s.riga else '-'} | {s.chi} | {s.motivo}" for s in risultato.scarti])
    sezione("IMPORTI NEGATIVI", [
        f"riga {m.riga} | {m.etichetta} | voce {m.voce} | {formatta_euro(m.importo_cent)} EUR"
        for m in prep.negativi])
    scelta = {True: "INCLUSE nel file", False: "ESCLUSE dal file", None: "scelta non fatta"}[
        includi_fuori_periodo]
    sezione(f"DATE FUORI PERIODO - {scelta}", [
        f"riga {m.riga} | {m.etichetta} | voce {m.voce} | {formatta_euro(m.importo_cent)} EUR "
        f"| {m.motivo_fuori}" for m in prep.fuori_periodo])
    sezione("AVVISI", risultato.avvisi)
    return "\n".join(righe)
