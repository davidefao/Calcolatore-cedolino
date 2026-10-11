"""Righe ripetute: rilevamento, scelta dell'utente (tenere o togliere) e interazioni."""
import io

import openpyxl
import pytest

from engine.converter import carica_config, genera, prepara
from engine.reader import RigaLetta, TabellaLetta, leggi_file
from engine.riconciliazione import (Anagrafica, CatalogoVoci, Dipendente, RigaCodice,
                                    carica_anagrafica, carica_catalogo)
from engine.servizio import (CARTELLA_CONFIG, conta_cose_da_controllare, converti_file,
                             log_anomalie, messaggio_duplicato, tabella_duplicati)

DITTA, PERIODO = 4012, "202609"
COLONNE = ["CF", "Nome", "Importo", "Data", "Trattamento", "Servizio"]
CONFIG = {
    "nome": "Provider di prova",
    "file": {"riga_intestazione": 1},
    "data": {"colonna": "Data", "formato": "%d/%m/%Y"},
    "importo": {"colonna": "Importo", "decimale": ",", "migliaia": "."},
    "dipendente": {"tipo": "codice_fiscale", "colonne": ["CF"], "etichetta": ["Nome"]},
    "trattamento": {"colonne": ["Trattamento"], "sottocategoria": None, "eccezioni": []},
}
# provider del kit: (config, ditta, file di esempio)
PROVIDER_KIT = [
    ("a", 4012, "ProviderA_welfare_report_2026-09-01_2026-09-30.xlsx"),
    ("b", 4027, "ProviderB_Flusso-Payroll-01_10_2026.csv"),
    ("c", 4041, "ProviderC_Erogazioni_fatt_031900.xls"),
    ("d", 4093, "ProviderD_tracciato_set26.csv"),
    ("e", 4131, "ProviderE_welfare_settembre_2026.xlsx"),
]


def _riga(cf="RSSMRA80A01H501U", nome="Rossi Mario", importo="10,00",
          data="03/09/2026", trattamento="Art. 51 c.3", servizio=""):
    return [cf, nome, importo, data, trattamento, servizio]


def _tabella(righe):
    return TabellaLetta(
        colonne=COLONNE, formato="csv",
        righe=[RigaLetta(i + 2, dict(zip(COLONNE, r))) for i, r in enumerate(righe)])

ANAGRAFICA = Anagrafica([Dipendente("4", "Rossi Mario", "RSSMRA80A01H501U"),
                         Dipendente("10", "Bianchi Anna", "BNCNNA85C41F205Z")])
CATALOGO = CatalogoVoci([RigaCodice("Art. 51 c.3", "371", "")])
BIANCHI = dict(cf="BNCNNA85C41F205Z", nome="Bianchi Anna")


def _prepara(righe):
    return prepara(_tabella(righe), CONFIG, DITTA, PERIODO, ANAGRAFICA, CATALOGO)


def test_tre_righe_identiche_formano_un_solo_gruppo():
    prep = _prepara([_riga(), _riga(), _riga()])
    assert len(prep.duplicati) == 1
    g = prep.duplicati[0]
    assert g.righe == [2, 3, 4] and g.volte == 3
    assert (g.etichetta, g.voce, g.importo_cent) == ("Rossi Mario", "371", 1000)
    assert [m.duplicato for m in prep.movimenti] == [False, True, True]


def test_tenere_somma_tutte_le_copie_togliere_ne_lascia_una():
    prep = _prepara([_riga(), _riga(), _riga()])
    tieni = genera(prep, DITTA, PERIODO, tieni_duplicati=True)
    togli = genera(prep, DITTA, PERIODO, tieni_duplicati=False)
    assert tieni.righe_output == ["0040124     371 0000000000003000202609"]    # 30,00
    assert togli.righe_output == ["0040124     371 0000000000001000202609"]    # 10,00
    assert (tieni.duplicati_rimossi, togli.duplicati_rimossi) == (0, 2)
    assert togli.movimenti_inclusi == 1


def test_senza_scelta_il_comportamento_di_prima_non_cambia():
    prep = _prepara([_riga(), _riga()])
    assert genera(prep, DITTA, PERIODO).totale_cent == 2000


def test_righe_che_differiscono_anche_di_una_sola_colonna_non_sono_duplicati():
    prep = _prepara([_riga(servizio="A"), _riga(servizio="B"), _riga(importo="10,01")])
    assert prep.duplicati == []


def test_gruppi_distinti_restano_distinti():
    prep = _prepara([_riga(), _riga(), _riga(importo="5,00", **BIANCHI), _riga(importo="5,00", **BIANCHI),
                     _riga(importo="7,00")])
    assert [g.righe for g in prep.duplicati] == [[2, 3], [4, 5]]
    assert genera(prep, DITTA, PERIODO, tieni_duplicati=False).duplicati_rimossi == 2


def test_la_stessa_riga_non_consecutiva_e_comunque_un_duplicato():
    prep = _prepara([_riga(), _riga(importo="7,00"), _riga()])
    assert prep.duplicati[0].righe == [2, 4]


def test_righe_ripetute_ma_scartate_non_sono_segnalate_come_duplicati():
    prep = _prepara([_riga(cf="XXXXXXXXXXXXXXXX"), _riga(cf="XXXXXXXXXXXXXXXX")])
    assert prep.duplicati == [] and len(prep.scarti) == 2


def test_duplicati_fuori_periodo_esclusi_non_contano_due_volte():
    prep = _prepara([_riga(data="01/08/2026"), _riga(data="01/08/2026"), _riga()])
    ris = genera(prep, DITTA, PERIODO, includi_fuori_periodo=False, tieni_duplicati=False)
    assert ris.movimenti_esclusi == 2 and ris.duplicati_rimossi == 0
    assert ris.totale_cent == 1000


def test_le_due_scelte_si_combinano_in_modo_indipendente():
    prep = _prepara([_riga(), _riga(), _riga(data="01/08/2026"), _riga(data="01/08/2026")])
    totali = {(i, t): genera(prep, DITTA, PERIODO, i, t).totale_cent
              for i in (True, False) for t in (True, False)}
    assert totali == {(True, True): 4000, (True, False): 2000,
                      (False, True): 2000, (False, False): 1000}


def test_negativi_ripetuti_sono_segnalati_come_duplicati():
    prep = _prepara([_riga(importo="-5,00"), _riga(importo="-5,00"), _riga(importo="30,00")])
    assert prep.duplicati[0].importo_cent == -500
    assert genera(prep, DITTA, PERIODO, tieni_duplicati=False).totale_cent == 2500
    assert genera(prep, DITTA, PERIODO, tieni_duplicati=True).totale_cent == 2000


def test_messaggio_per_l_utente():
    g = _prepara([_riga(), _riga()]).duplicati[0]
    assert messaggio_duplicato(g) == (
        "La riga 2 (Rossi Mario, voce 371, 10,00 €) è presente 2 volte (righe 2, 3).")


def test_tabella_dei_duplicati():
    prep = _prepara([_riga(), _riga(), _riga()])
    assert tabella_duplicati(prep) == [{
        "Righe nel file": "2, 3, 4", "Dipendente": "Rossi Mario", "Voce": "371",
        "Importo (€)": "10,00", "Data": "03/09/2026", "Presente": "3 volte"}]


def test_i_duplicati_contano_tra_le_cose_da_controllare_e_finiscono_nel_log():
    prep = _prepara([_riga(), _riga()])
    ris = genera(prep, DITTA, PERIODO, tieni_duplicati=False)
    assert conta_cose_da_controllare(prep, ris) == 1
    log = log_anomalie("Provider di prova", DITTA, PERIODO, prep, ris, True, False)
    assert "RIGHE RIPETUTE - TOLTE le copie" in log
    assert "è presente 2 volte" in log
    assert "RIGHE RIPETUTE - scelta non fatta" in log_anomalie(
        "P", DITTA, PERIODO, prep, ris, True, None)


def test_file_senza_duplicati_non_chiede_niente():
    prep = _prepara([_riga(), _riga(importo="7,00")])
    assert prep.duplicati == []
    assert conta_cose_da_controllare(prep, genera(prep, DITTA, PERIODO)) == 0


@pytest.mark.parametrize("chiave, ditta, nome_file", PROVIDER_KIT)
def test_nessun_file_del_kit_contiene_righe_ripetute(dato, chiave, ditta, nome_file):
    config = carica_config(CARTELLA_CONFIG / f"provider_{chiave}.json")
    f = dato(nome_file)
    prep = prepara(
        leggi_file(f.read_bytes(), f.name, config["file"]), config, ditta, PERIODO,
        carica_anagrafica(dato("Lista_Dipendenti.csv").read_bytes(), ditta),
        carica_catalogo(dato("Codici_Welfare_Voci_Payroll.csv").read_bytes()))
    assert prep.duplicati == []


def test_end_to_end_provider_a_con_una_riga_copiata_nel_file(dato):
    f = dato("ProviderA_welfare_report_2026-09-01_2026-09-30.xlsx")
    wb = openpyxl.load_workbook(f)
    ws = wb.active
    ws.append([c.value for c in ws[5]])            # copia identica della prima riga di dati
    buffer = io.BytesIO()
    wb.save(buffer)

    prep = converti_file(CARTELLA_CONFIG / "provider_a.json", buffer.getvalue(), "a.xlsx",
                         4012, PERIODO)
    assert len(prep.duplicati) == 1
    g = prep.duplicati[0]
    assert g.righe == [5, 26] and g.importo_cent == 15100
    base = genera(prep, 4012, PERIODO, tieni_duplicati=False)
    tutte = genera(prep, 4012, PERIODO, tieni_duplicati=True)
    assert base.totale_cent == 193386                      # come il file originale
    assert tutte.totale_cent == 193386 + 15100
    assert "0040124     373 0000000000015100202609" in base.righe_output
    assert "0040124     373 0000000000030200202609" in tutte.righe_output
    assert "0040124     373 0000000000015100202609" not in tutte.righe_output
