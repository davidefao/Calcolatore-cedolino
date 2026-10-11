import copy

import pytest

from engine.converter import (ErroreConfigurazione, carica_config, genera, prepara)
from engine.parsing import ErroreDato
from engine.reader import leggi_file
from engine.riconciliazione import carica_anagrafica, carica_catalogo

from conftest import CONFIGS

DITTA, PERIODO = 4012, "202609"
RIGA_FUMAGALLI = "00401225"


@pytest.fixture
def provider_a(dato):
    config = carica_config(CONFIGS / "provider_a.json")
    anagrafica = carica_anagrafica(dato("Lista_Dipendenti.csv").read_bytes(), DITTA)
    catalogo = carica_catalogo(dato("Codici_Welfare_Voci_Payroll.csv").read_bytes())
    f = dato("ProviderA_welfare_report_2026-09-01_2026-09-30.xlsx")
    tabella = leggi_file(f.read_bytes(), f.name, config["file"])
    return config, tabella, anagrafica, catalogo


def _prepara(provider_a, tabella=None):
    config, tab, ana, cat = provider_a
    return prepara(tabella or tab, config, DITTA, PERIODO, ana, cat)


def test_provider_a_coincide_con_l_esempio_tranne_il_dipendente_non_in_lista(provider_a, dato):
    risultato = genera(_prepara(provider_a), DITTA, PERIODO)
    attese = (dato("ESEMPIO_VOCI_4012_202609.txt").read_text().splitlines())
    attese = [r for r in attese if r]
    assert len(attese) == 19
    assert risultato.righe_output == [r for r in attese if not r.startswith(RIGA_FUMAGALLI)]


def test_fumagalli_e_scartata_con_messaggio_chiaro(provider_a):
    risultato = genera(_prepara(provider_a), DITTA, PERIODO)
    assert len(risultato.scarti) == 1
    s = risultato.scarti[0]
    assert s.riga == 8
    assert "Fumagalli" in s.chi
    assert "non presente nella ditta 4012" in s.motivo


def test_match_approssimato_segnalato_tra_gli_avvisi(provider_a):
    risultato = genera(_prepara(provider_a), DITTA, PERIODO)
    assert any("d-bis" in a and "377" in a for a in risultato.avvisi)


def test_formato_file_output(provider_a):
    testo = genera(_prepara(provider_a), DITTA, PERIODO).testo_output()
    assert testo.endswith("\r\n")
    righe = testo.split("\r\n")[:-1]
    assert len(righe) == 18
    assert all(len(r) == 38 and r.isascii() for r in righe)


def test_senza_date_fuori_periodo_la_scelta_non_cambia_nulla(provider_a):
    prep = _prepara(provider_a)
    assert prep.fuori_periodo == []
    assert (genera(prep, DITTA, PERIODO, True).righe_output
            == genera(prep, DITTA, PERIODO, False).righe_output)


def test_righe_fuori_periodo_rilevate_e_la_scelta_dell_utente_cambia_l_output(provider_a):
    _, tabella, _, _ = provider_a
    modificata = copy.deepcopy(tabella)
    modificata.righe[0].valori["Data"] = "2026-08-28"     # Bellini, 151,00
    modificata.righe[1].valori["Data"] = "2026-10-02"     # Mariani, 27,00
    prep = _prepara(provider_a, modificata)

    assert [m.riga for m in prep.fuori_periodo] == [5, 6]
    assert "agosto 2026" in prep.fuori_periodo[0].motivo_fuori
    assert "ottobre 2026" in prep.fuori_periodo[1].motivo_fuori

    base = genera(_prepara(provider_a), DITTA, PERIODO)
    con = genera(prep, DITTA, PERIODO, includi_fuori_periodo=True)
    senza = genera(prep, DITTA, PERIODO, includi_fuori_periodo=False)

    assert con.righe_output == base.righe_output                  # incluse: nulla cambia
    assert con.movimenti_esclusi == 0
    assert senza.movimenti_esclusi == 2
    assert senza.totale_cent == base.totale_cent - 15100 - 2700   # 151,00 + 27,00
    assert len(senza.righe_output) == len(base.righe_output) - 2  # due coppie sparite


def test_data_mancante_o_illeggibile_va_tra_i_fuori_periodo_non_negli_scarti(provider_a):
    _, tabella, _, _ = provider_a
    modificata = copy.deepcopy(tabella)
    modificata.righe[0].valori["Data"] = ""
    modificata.righe[1].valori["Data"] = "boh"
    prep = _prepara(provider_a, modificata)
    assert [m.riga for m in prep.fuori_periodo] == [5, 6]
    assert "mancante" in prep.fuori_periodo[0].motivo_fuori
    assert "non leggibile" in prep.fuori_periodo[1].motivo_fuori
    assert len(prep.scarti) == 1                                  # solo Fumagalli


def test_importo_non_valido_va_in_scarto_con_il_numero_di_riga(provider_a):
    _, tabella, _, _ = provider_a
    modificata = copy.deepcopy(tabella)
    modificata.righe[0].valori["Importo"] = "abc"
    prep = _prepara(provider_a, modificata)
    assert any(s.riga == 5 and "importo non valido" in s.motivo for s in prep.scarti)


def test_totale_negativo_non_entra_nel_file_e_va_in_scarto(provider_a):
    _, tabella, _, _ = provider_a
    modificata = copy.deepcopy(tabella)
    modificata.righe[0].valori["Importo"] = "-151,00"             # storno, nessun altro importo
    risultato = genera(_prepara(provider_a, modificata), DITTA, PERIODO)
    assert not any(r.startswith("0040124     373") for r in risultato.righe_output)
    assert any("dipendente 4" in s.chi and s.riga is None for s in risultato.scarti)


def test_importi_negativi_sono_elencati_per_l_avviso(provider_a):
    _, tabella, _, _ = provider_a
    modificata = copy.deepcopy(tabella)
    modificata.righe[0].valori["Importo"] = "-151,00"
    prep = _prepara(provider_a, modificata)
    assert [(m.riga, m.importo_cent) for m in prep.negativi] == [(5, -15100)]
    assert "Bellini" in prep.negativi[0].etichetta


def test_totale_negativo_spiega_il_motivo(provider_a):
    _, tabella, _, _ = provider_a
    modificata = copy.deepcopy(tabella)
    modificata.righe[0].valori["Importo"] = "-151,00"
    risultato = genera(_prepara(provider_a, modificata), DITTA, PERIODO)
    scarto = next(s for s in risultato.scarti if s.riga is None)
    assert "totale negativo (-151,00 €)" in scarto.motivo
    assert "non ammette importi negativi" in scarto.motivo


def test_storno_parziale_non_e_scarto_ma_e_segnalato(provider_a):
    # 151,00 - 50,00 = 101,00: il record esiste, ma la riga negativa va comunque mostrata
    _, tabella, _, _ = provider_a
    modificata = copy.deepcopy(tabella)
    storno = copy.deepcopy(modificata.righe[0])
    storno.numero = 99
    storno.valori["Importo"] = "-50,00"
    modificata.righe.append(storno)
    prep = _prepara(provider_a, modificata)
    risultato = genera(prep, DITTA, PERIODO)
    assert len(prep.negativi) == 1
    assert "0040124     373 0000000000010100202609" in risultato.righe_output
    assert len(risultato.scarti) == 1                      # solo Fumagalli


def test_importi_che_si_annullano_non_generano_record(provider_a):
    _, tabella, _, _ = provider_a
    modificata = copy.deepcopy(tabella)
    stessa = copy.deepcopy(modificata.righe[0])
    stessa.numero = 99
    stessa.valori["Importo"] = "-151,00"
    modificata.righe.append(stessa)
    risultato = genera(_prepara(provider_a, modificata), DITTA, PERIODO)
    assert not any(r.startswith("0040124     373") for r in risultato.righe_output)
    assert any("si annullano" in a for a in risultato.avvisi)


def test_ordinamento_numerico_dei_dipendenti(provider_a):
    righe = genera(_prepara(provider_a), DITTA, PERIODO).righe_output
    dipendenti = [int(r[6:12]) for r in righe]
    assert dipendenti == sorted(dipendenti)                       # 4, 10, 12... non 10, 12, 4


def test_periodo_non_valido_e_rifiutato(provider_a):
    config, tab, ana, cat = provider_a
    with pytest.raises(ErroreDato):
        prepara(tab, config, DITTA, "2026-09", ana, cat)


def test_colonna_inesistente_dice_quali_colonne_ci_sono(provider_a):
    config, tab, ana, cat = provider_a
    sbagliata = copy.deepcopy(config)
    sbagliata["importo"]["colonna"] = "Valore"
    with pytest.raises(ErroreConfigurazione, match="Colonne trovate"):
        prepara(tab, sbagliata, DITTA, PERIODO, ana, cat)


def test_configurazione_incompleta():
    with pytest.raises(ErroreConfigurazione, match="mancano"):
        carica_config('{"nome": "X"}')
    with pytest.raises(ErroreConfigurazione, match="JSON"):
        carica_config('{ non json')
