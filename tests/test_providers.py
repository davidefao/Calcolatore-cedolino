"""Test dei cinque provider sui file di esempio del kit.

I totali attesi sono stati calcolati a parte (con pandas, senza usare il motore):
totale lordo del file meno gli importi delle righe che devono essere scartate.
"""
import copy

import pytest

from engine.converter import carica_config, genera, prepara
from engine.reader import leggi_file
from engine.riconciliazione import carica_anagrafica, carica_catalogo

from conftest import CONFIGS

PERIODO = "202609"

# chiave, ditta, file, righe lette, movimenti, record, totale (centesimi), scarti attesi, una riga attesa
CASI = [
    ("b", 4027, "ProviderB_Flusso-Payroll-01_10_2026.csv", 12, 8, 6, 292940,
     [(7, "MARINI SOFIA"), (8, "MARINI SOFIA"), (9, "MARINI SOFIA"), (11, "DE SANTIS LAURA")],
     "00402715013 380 0000000000031178202609"),          # 99,61 + 212,17
    ("c", 4041, "ProviderC_Erogazioni_fatt_031900.xls", 20, 20, 17, 534693,
     [],
     "00404120    194 0000000000031210202609"),
    ("d", 4093, "ProviderD_tracciato_set26.csv", 17, 16, 12, 285326,
     [(11, "Matteo Martini")],
     "00409338    373 0000000000075181202609"),          # 400,09 (asilo nido) + 351,72
    ("e", 4131, "ProviderE_welfare_settembre_2026.xlsx", 19, 16, 11, 189710,
     [(4, "GUERRA PAOLO"), (13, "GUERRA PAOLO"), (20, "GUERRA PAOLO")],
     "00413115026 373 0000000000033100202609"),
]
NOMI = "chiave, ditta, nome_file, lette, movimenti, record, totale, scarti, riga"


def _esegui(dato, chiave, ditta, nome_file, config=None):
    config = config or carica_config(CONFIGS / f"provider_{chiave}.json")
    anagrafica = carica_anagrafica(dato("Lista_Dipendenti.csv").read_bytes(), ditta)
    catalogo = carica_catalogo(dato("Codici_Welfare_Voci_Payroll.csv").read_bytes())
    f = dato(nome_file)
    tabella = leggi_file(f.read_bytes(), f.name, config["file"])
    prep = prepara(tabella, config, ditta, PERIODO, anagrafica, catalogo)
    return prep, genera(prep, ditta, PERIODO)


@pytest.mark.parametrize(NOMI, CASI)
def test_provider_numeri_attesi(dato, chiave, ditta, nome_file, lette, movimenti,
                                record, totale, scarti, riga):
    prep, ris = _esegui(dato, chiave, ditta, nome_file)
    assert prep.righe_lette == lette
    assert len(prep.movimenti) == movimenti
    assert len(ris.righe_output) == record
    assert ris.totale_cent == totale
    assert [(s.riga, s.chi) for s in ris.scarti] == scarti
    assert riga in ris.righe_output


@pytest.mark.parametrize(NOMI, CASI)
def test_provider_nessun_importo_si_perde(dato, chiave, ditta, nome_file, lette, movimenti,
                                          record, totale, scarti, riga):
    """Tutto ciò che non è scartato finisce nel file: il totale torna con la somma dei movimenti."""
    prep, ris = _esegui(dato, chiave, ditta, nome_file)
    assert ris.totale_cent == sum(m.importo_cent for m in prep.movimenti)
    assert len(prep.movimenti) + len([s for s in ris.scarti if s.riga]) == prep.righe_lette


@pytest.mark.parametrize(NOMI, CASI)
def test_provider_formato_e_ordinamento(dato, chiave, ditta, nome_file, lette, movimenti,
                                        record, totale, scarti, riga):
    _, ris = _esegui(dato, chiave, ditta, nome_file)
    assert all(len(r) == 38 and r.isascii() for r in ris.righe_output)
    assert all(r.startswith(f"{ditta:06d}") and r.endswith(PERIODO) for r in ris.righe_output)
    chiavi = [(int(r[6:12]), int(r[12:16])) for r in ris.righe_output]
    assert chiavi == sorted(chiavi)
    assert len(set(chiavi)) == len(chiavi)                # un record per coppia dipendente/voce


@pytest.mark.parametrize(NOMI, CASI)
def test_provider_nessuna_data_fuori_periodo_nel_kit(dato, chiave, ditta, nome_file, lette,
                                                     movimenti, record, totale, scarti, riga):
    prep, _ = _esegui(dato, chiave, ditta, nome_file)
    assert prep.fuori_periodo == []
    assert prep.negativi == []


@pytest.mark.parametrize("chiave, ditta, nome_file", [
    ("b", 4027, "ProviderB_Flusso-Payroll-01_10_2026.csv"),
    ("e", 4131, "ProviderE_welfare_settembre_2026.xlsx"),
])
def test_ditta_sbagliata_scarta_tutto(dato, chiave, ditta, nome_file):
    """I dipendenti si cercano solo nella ditta indicata: con una ditta diversa non si trova nessuno."""
    _, ris = _esegui(dato, chiave, 4012, nome_file)
    assert ris.righe_output == []
    assert all("non presente nella ditta 4012" in s.motivo for s in ris.scarti)


# ------------------------------------------------ particolarità dei singoli provider

def test_b_voce_sconosciuta_ha_un_messaggio_chiaro(dato):
    _, ris = _esegui(dato, "b", 4027, "ProviderB_Flusso-Payroll-01_10_2026.csv")
    scarto = next(s for s in ris.scarti if s.riga == 11)
    assert "X71133" in scarto.motivo and "non presente nei codici" in scarto.motivo


def test_c_sottocategoria_effettivo_figurativo(dato):
    _, ris = _esegui(dato, "c", 4041, "ProviderC_Erogazioni_fatt_031900.xls")
    assert any("00404120    194" in r for r in ris.righe_output)     # c.3 Effettivo -> 194
    assert any("00404150    371" in r for r in ris.righe_output)     # c.3 Figurativo -> caso base
    assert any("«Art.51 c. 3»" in a and "371" in a for a in ris.avvisi)


def test_c_matricola_con_zeri_iniziali(dato):
    _, ris = _esegui(dato, "c", 4041, "ProviderC_Erogazioni_fatt_031900.xls")
    assert all(not r[6:12].startswith("0") for r in ris.righe_output)  # 00000020 -> 20


def test_d_asilo_nido_usa_l_eccezione_della_config(dato):
    prep, ris = _esegui(dato, "d", 4093, "ProviderD_tracciato_set26.csv")
    assert ris.avvisi == []


def test_d_senza_eccezione_l_asilo_nido_e_uno_scarto_esplicito(dato):
    config = carica_config(CONFIGS / "provider_d.json")
    config = copy.deepcopy(config)
    config["trattamento"]["eccezioni"] = []
    _, ris = _esegui(dato, "d", 4093, "ProviderD_tracciato_set26.csv", config)
    motivi = [s.motivo for s in ris.scarti if s.riga == 2]
    assert motivi and "ambigua" in motivi[0] and "372, 373" in motivi[0]


def test_e_usa_il_totale_importo_per_quantita(dato):
    """Dipendente 15000, voce 371: 68,00 (1 x 68,00) + 27,94 (2 x 13,97) = 95,94."""
    _, ris = _esegui(dato, "e", 4131, "ProviderE_welfare_settembre_2026.xlsx")
    assert "00413115000 371 0000000000009594202609" in ris.righe_output


def test_e_match_approssimato_art_100_iva_segnalato(dato):
    _, ris = _esegui(dato, "e", 4131, "ProviderE_welfare_settembre_2026.xlsx")
    assert any("Iva 22%" in a and "370" in a for a in ris.avvisi)


# ------------------------------------------------ tutte le configurazioni

@pytest.mark.parametrize("chiave", ["a", "b", "c", "d", "e"])
def test_le_configurazioni_sono_valide(chiave):
    config = carica_config(CONFIGS / f"provider_{chiave}.json")
    assert config["nome"] == f"Provider {chiave.upper()}"
