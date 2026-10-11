"""Interpretazione dei testi letti dal reader: importi, date, trattamenti, nomi.

Qui, e solo qui, si decide cosa significa un testo. Il reader non interpreta
nulla; il motore chiede a queste funzioni.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import Decimal

from engine.formatter import euro_a_centesimi


class ErroreDato(ValueError):
    """Un valore del file non è interpretabile. Il messaggio va nel log."""


# ---------------------------------------------------------------- importi

_SOLO_NUMERO = re.compile(r"^\d+(\.\d+)?$")


def importo_a_centesimi(testo: str, decimale: str = ",", migliaia: str = "") -> int:
    """'1.234,56' (decimale=',', migliaia='.') -> 123456. Mai float.

    Accetta simboli di valuta, spazi, segno meno davanti o dietro e parentesi
    contabili. Se il formato non torna con la configurazione dà errore:
    meglio uno scarto visibile che un importo letto male in silenzio.
    """
    originale = testo
    t = re.sub(r"[€$£\s\u00a0]", "", (testo or ""))
    if not t:
        raise ErroreDato("importo vuoto")

    negativo = False
    if t.startswith("(") and t.endswith(")"):
        negativo, t = True, t[1:-1]
    if t.startswith("-"):
        negativo, t = True, t[1:]
    elif t.startswith("+"):
        t = t[1:]
    if t.endswith("-"):
        negativo, t = True, t[:-1]

    if migliaia:
        t = t.replace(migliaia, "")
    if decimale != ".":
        t = t.replace(decimale, ".")

    if not _SOLO_NUMERO.match(t):
        raise ErroreDato(f"importo non valido: «{originale}»")

    if len(t.split(".")[0]) > 12:
        raise ErroreDato(f"importo troppo grande: «{originale}»")
    valore = Decimal(t)
    # Più di due decimali "veri" = probabile errore di formato (es. 1,234.56 letto con
    # separatori invertiti). Il rumore dei float di Excel (0.30000000000000004) è tollerato.
    if abs(valore - valore.quantize(Decimal("0.01"))) > Decimal("0.000001"):
        raise ErroreDato(
            f"importo con più di due decimali: «{originale}» "
            "(controlla il formato degli importi nella configurazione)"
        )
    return euro_a_centesimi(-valore if negativo else valore)


# ---------------------------------------------------------------- date

def data_a_periodo(testo: str, formato: str) -> int:
    """Restituisce il mese della data nella forma AAAAMM (es. 202609)."""
    t = (testo or "").strip()
    if not t:
        raise ErroreDato("data vuota")
    if " " in t and " " not in formato:      # "2026-09-03 10:30:00" con formato solo-data
        t = t.split()[0]
    try:
        d = datetime.strptime(t, formato)
    except ValueError:
        # le celle data di Excel arrivano dal reader in forma ISO (AAAA-MM-GG)
        m = re.fullmatch(r"([0-9]{4})-([0-9]{2})-([0-9]{2})(?:[ T].*)?", t)
        try:
            if not m:
                raise ValueError
            d = datetime(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            raise ErroreDato(f"data non leggibile: «{testo}»") from None
    return d.year * 100 + d.month


def periodo_a_testo(periodo: str) -> str:
    """'202609' -> 'settembre 2026'."""
    mesi = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
            "agosto", "settembre", "ottobre", "novembre", "dicembre"]
    return f"{mesi[int(periodo[4:]) - 1]} {periodo[:4]}"


def valida_periodo(periodo: str) -> str:
    """Controlla che il periodo sia AAAAMM con mese 01-12."""
    p = (periodo or "").strip()
    if not re.fullmatch(r"[0-9]{6}", p) or not 1 <= int(p[4:]) <= 12:
        raise ErroreDato("Il periodo deve essere nel formato AAAAMM, ad esempio 202609.")
    return p


# ---------------------------------------------------------------- testi

_PAROLE_RUMORE = re.compile(r"\b(benefit|tuir|consumo|fringe|voucher|richiesta)\b")


def normalizza_trattamento(testo: str) -> str:
    """Forma 'canonica' per confrontare scritture diverse dello stesso articolo.

    'Benefit art.51 c.2 let d-bis'  e  'Art. 51 c.2 lett. d-bis'  -> 'art51c2dbis'
    'Art.51 c. 2, f bis'                                          -> 'art51c2fbis'
    """
    t = (testo or "").lower()
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", t)      # (ex Art.100), [FCI Art.74]
    t = _PAROLE_RUMORE.sub(" ", t)
    t = re.sub(r"\bco\b", "c", t)                    # "co. 2" -> "c 2"
    t = re.sub(r"\blet{1,2}\b", " ", t)              # "let" / "lett"
    return re.sub(r"[^a-z0-9]", "", t)


def chiave_nome(testo: str) -> str:
    """Chiave per confrontare nomi, indifferente a ordine, maiuscole, accenti, apostrofi e spazi.

    'Gian Luca Bellini' = 'BELLINI GIAN LUCA';  "D'Angelo" = 'Dangelo';  'De Santis' = 'Desantis';
    'Niccolò' = 'Niccolo'. Si confrontano le lettere ordinate: il confronto resta sempre dentro
    la ditta e, se due dipendenti dessero la stessa chiave, il motore segnala l'ambiguità.
    """
    t = unicodedata.normalize("NFKD", (testo or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return "".join(sorted(re.sub(r"[^a-z]", "", t)))


def chiave_codice(testo: str) -> str:
    """'00000020' e '20' sono lo stesso codice; i codici non numerici restano uguali."""
    t = (testo or "").strip()
    return str(int(t)) if t.isascii() and t.isdigit() else t.upper()
