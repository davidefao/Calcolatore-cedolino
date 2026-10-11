import pytest

from engine.parsing import (ErroreDato, chiave_codice, chiave_nome, data_a_periodo,
                            importo_a_centesimi, normalizza_trattamento, valida_periodo)


@pytest.mark.parametrize("testo, decimale, migliaia, atteso", [
    ("151,00", ",", "", 15100),
    ("3103,27", ",", "", 310327),
    ("1.234,56", ",", ".", 123456),
    ("€68.00", ".", "", 6800),
    ("312.1", ".", "", 31210),          # float Excel convertito in testo
    ("566", ".", "", 56600),
    ("0.30000000000000004", ".", "", 30),   # residuo di float: si arrotonda ai centesimi
    ("-25,50", ",", "", -2550),
    ("25,50-", ",", "", -2550),
    ("(25,50)", ",", "", -2550),
])
def test_importi_validi(testo, decimale, migliaia, atteso):
    assert importo_a_centesimi(testo, decimale, migliaia) == atteso


@pytest.mark.parametrize("testo", ["", "abc", "1.234,56", "12,3,4", "NaN", "1e5"])
def test_importi_non_validi_non_vengono_indovinati(testo):
    # "1.234,56" senza migliaia dichiarate è un errore, non un importo letto male
    with pytest.raises(ErroreDato):
        importo_a_centesimi(testo, ",", "")


def test_date():
    assert data_a_periodo("2026-09-03", "%Y-%m-%d") == 202609
    assert data_a_periodo("20260924", "%Y%m%d") == 202609
    assert data_a_periodo("13/09/2026", "%d/%m/%Y") == 202609
    assert data_a_periodo("2026-09-03 10:30:00", "%Y-%m-%d") == 202609
    with pytest.raises(ErroreDato):
        data_a_periodo("31/02/2026", "%d/%m/%Y")
    with pytest.raises(ErroreDato):
        data_a_periodo("", "%d/%m/%Y")


def test_periodo():
    assert valida_periodo("202609") == "202609"
    for sbagliato in ["2026-09", "202613", "202600", "26", ""]:
        with pytest.raises(ErroreDato):
            valida_periodo(sbagliato)


def test_normalizzazione_trattamenti():
    uguali = ["Benefit art.51 c.2 let d-bis", "Art. 51 c.2 lett. d-bis", 'Art.51 c. 2, d bis']
    assert len({normalizza_trattamento(t) for t in uguali}) == 1
    assert normalizza_trattamento("Art. 51 co. 2 lett. h") == normalizza_trattamento("Art. 51 c.2 lett. h")
    assert normalizza_trattamento("Art.100 [FCI Art.74]") == normalizza_trattamento("Art 100 [Iva 22%]")
    assert normalizza_trattamento("Art. 51 c.3") != normalizza_trattamento("Art. 51 c.2 lett. f")


def test_chiavi():
    assert chiave_nome("Gian Luca Bellini") == chiave_nome("BELLINI GIAN LUCA")
    assert chiave_codice("00000020") == chiave_codice("20") == "20"
    assert chiave_codice("x71180") == "X71180"
