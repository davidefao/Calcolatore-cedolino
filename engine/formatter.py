from decimal import Decimal, ROUND_HALF_UP

LUNGHEZZA_RECORD = 38


def euro_a_centesimi(importo: Decimal) -> int:
    """Converte un importo in euro in centesimi interi (22.44 -> 2244)."""
    return int((importo * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _num(valore: int, lunghezza: int) -> str:
    """Numerico: allineato a destra, zeri a sinistra."""
    if valore < 0:
        raise ValueError(f"Valore negativo non gestito: {valore}")
    testo = str(valore).rjust(lunghezza, "0")
    if len(testo) > lunghezza:
        raise ValueError(f"Valore {valore} troppo grande per {lunghezza} cifre")
    return testo


def _alfa(valore: str, lunghezza: int) -> str:
    """Alfanumerico: allineato a sinistra, spazi a destra."""
    valore = str(valore).strip()
    if len(valore) > lunghezza:
        raise ValueError(f"'{valore}' più lungo di {lunghezza} caratteri")
    if not valore.isascii():
        raise ValueError(f"'{valore}' contiene caratteri non ASCII")
    return valore.ljust(lunghezza)


def formatta_record(ditta: int, dipendente: str, voce: str,
                    importo_cent: int, periodo: str) -> str:
    """Costruisce una riga del tracciato VOCI (38 caratteri)."""
    if len(periodo) != 6 or not periodo.isdigit():
        raise ValueError(f"Periodo non valido: {periodo}")
    riga = (
        _num(int(ditta), 6)        # pos 1-6   codice ditta
        + _alfa(dipendente, 6)     # pos 7-12  codice dipendente
        + _alfa(voce, 4)           # pos 13-16 codice voce
        + _num(0, 7)               # pos 17-23 quantità (sempre zeri)
        + _num(importo_cent, 9)    # pos 24-32 importo
        + periodo                  # pos 33-38 periodo
    )
    assert len(riga) == LUNGHEZZA_RECORD
    return riga