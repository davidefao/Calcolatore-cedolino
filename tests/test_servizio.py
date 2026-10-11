from datetime import date

import pytest

from engine.converter import genera
from engine.parsing import ErroreDato
from engine.servizio import (CARTELLA_CONFIG, ErroreInstallazione, converti_file,
                             elenca_provider, formatta_euro, nome_file_output,
                             periodo_predefinito, tabella_scarti, log_anomalie, valida_ditta)


@pytest.mark.parametrize("centesimi, atteso", [
    (0, "0,00"), (5, "0,05"), (123456, "1.234,56"), (100000000, "1.000.000,00"), (-5, "-0,05"),
])
def test_formatta_euro(centesimi, atteso):
    assert formatta_euro(centesimi) == atteso


def test_valida_ditta():
    assert valida_ditta(" 4012 ") == 4012
    for sbagliata in ["", "abc", "40 12", "1234567", "0", "-5"]:
        with pytest.raises(ErroreDato):
            valida_ditta(sbagliata)


def test_periodo_predefinito_e_il_mese_precedente():
    assert periodo_predefinito(date(2026, 10, 11)) == "202609"
    assert periodo_predefinito(date(2026, 1, 5)) == "202512"


def test_nome_file_output():
    assert nome_file_output(4012, "202609") == "VOCI_4012_202609.txt"


def test_elenco_provider():
    provider = elenca_provider()
    assert list(provider) == ["Provider A", "Provider B", "Provider C", "Provider D", "Provider E"]
    assert all(p.parent == CARTELLA_CONFIG for p in provider.values())


def test_conversione_completa_del_provider_a(dato):
    f = dato("ProviderA_welfare_report_2026-09-01_2026-09-30.xlsx")
    prep = converti_file(CARTELLA_CONFIG / "provider_a.json", f.read_bytes(), f.name, 4012, "202609")
    ris = genera(prep, 4012, "202609")
    assert len(ris.righe_output) == 18
    assert tabella_scarti(ris)[0]["Dipendente"] == "Alessia Fumagalli"


def test_file_di_riconciliazione_mancante_non_e_colpa_dell_utente(dato, tmp_path):
    f = dato("ProviderA_welfare_report_2026-09-01_2026-09-30.xlsx")
    with pytest.raises(ErroreInstallazione, match="riconciliazione"):
        converti_file(CARTELLA_CONFIG / "provider_a.json", f.read_bytes(), f.name,
                      4012, "202609", cartella_riconciliazione=tmp_path)


def test_log_contiene_scarti_e_scelta_sulle_date(dato):
    f = dato("ProviderA_welfare_report_2026-09-01_2026-09-30.xlsx")
    prep = converti_file(CARTELLA_CONFIG / "provider_a.json", f.read_bytes(), f.name, 4012, "202609")
    ris = genera(prep, 4012, "202609")
    log = log_anomalie("Provider A", 4012, "202609", prep, ris, True)
    assert "settembre 2026" in log
    assert "riga 8 | Alessia Fumagalli | dipendente non presente nella ditta 4012" in log
    assert "DATE FUORI PERIODO - INCLUSE nel file (0)" in log
