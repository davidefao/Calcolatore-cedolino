import pytest

from engine.riconciliazione import (Anagrafica, CatalogoVoci, Dipendente,
                                    ErroreRiconciliazione, RigaCodice,
                                    carica_anagrafica, carica_catalogo)

LISTA = (
    "Codice Ditta,CodAnagraficoLav,Nome Dipendente,CodiceFiscale,RagioneSociale\n"
    "4012,4,Bellini Gian Luca,BLLGLC87B23B354L,Alfa\n"
    "4012,4,Bellini Gian Luca,BLLGLC87B23B354L,Alfa\n"       # doppione esatto
    "4012,20,Conte Beatrice,CNTBRC99M65C351H,Alfa\n"
    "4175,900,Noemi La Rocca,LRCNMO75P50H501M,Tiglio\n"
    "4012,10,Noemi La Rocca,LRCNMO75P50H501M,Alfa\n"          # stesso CF in due ditte
    "4012,30,Mario Rossi,RSSMRA80A01H501U,Alfa\n"
    "4012,31,Rossi Mario,RSSMRA81A01H501U,Alfa\n"             # stesso nome, due persone
).encode()


def test_anagrafica_solo_la_ditta_richiesta_e_senza_doppioni():
    ana = carica_anagrafica(LISTA, 4012)
    assert len(ana.dipendenti) == 5
    assert ana.trova("codice_fiscale", "LRCNMO75P50H501M").codice == "10"
    assert carica_anagrafica(LISTA, 4175).trova("codice_fiscale", "LRCNMO75P50H501M").codice == "900"


def test_anagrafica_tre_tipi_di_chiave():
    ana = carica_anagrafica(LISTA, 4012)
    assert ana.trova("codice_fiscale", "bllglc87b23b354l").codice == "4"
    assert ana.trova("codice", "00000020").codice == "20"          # zeri iniziali
    assert ana.trova("nome", "BELLINI  GIAN LUCA").codice == "4"
    assert ana.trova("nome", "Gian Luca Bellini").codice == "4"    # ordine diverso


def test_anagrafica_non_trovato_e_ambiguo():
    ana = carica_anagrafica(LISTA, 4012)
    with pytest.raises(ErroreRiconciliazione, match="non presente nella ditta 4012"):
        ana.trova("codice_fiscale", "FMGLSS92S52G273A", "4012")
    with pytest.raises(ErroreRiconciliazione, match="ambiguo"):
        ana.trova("nome", "Mario Rossi", "4012")
    with pytest.raises(ErroreRiconciliazione, match="vuota"):
        ana.trova("codice", "")


CODICI = [
    RigaCodice("Art. 51 c.3", "371", ""),
    RigaCodice("Art. 51 c.3", "371", ""),
    RigaCodice("Art.51 c. 3", "194", "Effettivo"),
    RigaCodice("Art. 51 c.2 lett. f-bis", "375", "Centri estivi"),
    RigaCodice("Art. 51 c.2 lett. f-bis", "373", "Istruzione"),
    RigaCodice("Art. 51 c2 lett f-bis", "373", ""),
    RigaCodice("Art.51 c. 2, f bis", "372", ""),
    RigaCodice("Art. 51 c.2 lett. d-bis", "377", ""),
    RigaCodice("X71180", "380", ""),
]


def test_voce_match_esatto():
    cat = CatalogoVoci(CODICI)
    assert cat.trova("X71180") == ("380", None)
    assert cat.trova("Art. 51 c.3") == ("371", None)


def test_voce_sottocategoria_esistente():
    cat = CatalogoVoci(CODICI)
    assert cat.trova("Art. 51 c.2 lett. f-bis", "Istruzione") == ("373", None)
    assert cat.trova("Art.51 c. 3", "Effettivo") == ("194", None)


def test_voce_sottocategoria_inesistente_usa_il_caso_base():
    cat = CatalogoVoci(CODICI)
    codice, avviso = cat.trova("Art.51 c. 3", "Figurativo")
    assert codice == "371" and avviso            # base trovato per somiglianza, segnalato


def test_voce_match_approssimato_e_segnalato():
    cat = CatalogoVoci(CODICI)
    codice, avviso = cat.trova("Benefit art.51 c.2 let d-bis")
    assert codice == "377"
    assert "somiglianza" in avviso


def test_voce_senza_caso_base_e_errore():
    cat = CatalogoVoci([RigaCodice("Art. 51 c.2 lett. h", "382", "Solo sub")])
    with pytest.raises(ErroreRiconciliazione):
        cat.trova("Art. 51 c.2 lett. h")


def test_voce_casi_base_discordanti_e_errore_ma_l_eccezione_risolve():
    cat = CatalogoVoci(CODICI)
    with pytest.raises(ErroreRiconciliazione, match="ambigua"):
        cat.trova("Art. 51 c.2 lett. f-bis", "Asilo nido")
    eccezioni = [{"trattamento": "Art. 51 c.2 lett. f-bis", "sottocategoria": "Asilo nido", "voce": "373"}]
    assert cat.trova("Art. 51 c.2 lett. f-bis", "Asilo nido", eccezioni) == ("373", None)


def test_voce_non_presente():
    with pytest.raises(ErroreRiconciliazione, match="non presente"):
        CatalogoVoci(CODICI).trova("X71133")


def test_catalogo_dal_file_vero(dato):
    cat = carica_catalogo(dato("Codici_Welfare_Voci_Payroll.csv").read_bytes())
    assert len(cat.righe) == 36
    assert cat.trova("Art.51 c. 2, f bis") == ("372", None)       # virgola dentro le virgolette
    assert cat.trova("Art. 51 c.2 lett. f-bis", "Istruzione non universitaria") == ("373", None)


def test_anagrafica_dal_file_vero(dato):
    ana = carica_anagrafica(dato("Lista_Dipendenti.csv").read_bytes(), 4012)
    assert len(ana.dipendenti) == 11
