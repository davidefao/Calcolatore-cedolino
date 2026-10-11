"""Convertitore welfare: dal report del provider al file voci per le paghe.

Questa pagina disegna soltanto l'interfaccia: tutta la logica sta in engine/.
"""
import streamlit as st

from engine.converter import ErroreConfigurazione, genera
from engine.parsing import ErroreDato, periodo_a_testo, valida_periodo
from engine.reader import ErroreLettura
from engine.riconciliazione import ErroreInstallazione
from engine.servizio import (ErroreDitta, conta_cose_da_controllare, converti_file,
                             elenca_provider, formatta_euro, log_anomalie,
                             messaggio_duplicato, nome_file_output, periodo_predefinito,
                             tabella_duplicati, tabella_movimenti, tabella_scarti,
                             valida_ditta)

SCELTA_INCLUDI = "Sì, includile nel file"
SCELTA_ESCLUDI = "No, escludile dal file"
SCELTA_TIENI = "Tieni tutte le copie"
SCELTA_TOGLI = "Togli le copie (ne resta una per riga)"


def _righe(n, singolare, plurale):
    """'1 riga ...' / '3 righe ...': accorda il testo al numero."""
    return f"{n} {singolare if n == 1 else plurale}"


def _firma(provider, ditta_txt, periodo_txt, file):
    """Identifica i dati usati per l'ultima conversione, per accorgerci se cambiano."""
    return (provider, ditta_txt.strip(), periodo_txt.strip(),
            file.name if file else None, file.size if file else None)


def _converti(provider, percorso_config, ditta_txt, periodo_txt, file):
    """Controlla i dati inseriti, esegue la conversione e ricorda l'esito."""
    st.session_state.pop("esito", None)                     # un eventuale esito vecchio non vale più
    try:
        ditta = valida_ditta(ditta_txt)
        periodo = valida_periodo(periodo_txt)
    except ErroreDato as e:
        st.error(str(e))
        return
    if file is None:
        st.error("Scegli il file del provider da convertire.")
        return

    try:
        with st.spinner("Sto leggendo il file…"):
            prep = converti_file(percorso_config, file.getvalue(), file.name, ditta, periodo)
    except (ErroreLettura, ErroreDato) as e:
        st.error(f"Non riesco a leggere il file. {e}")
        return
    except ErroreDitta as e:
        st.error(str(e))
        return
    except ErroreInstallazione as e:
        st.error(f"Problema dell'applicazione, non del tuo file. {e}")
        return
    except ErroreConfigurazione as e:
        st.error(f"Il file non corrisponde a quello che mi aspetto da {provider}. {e} "
                 "Controlla di aver scelto il provider giusto.")
        return
    except Exception as e:                                  # rete di sicurezza: mai una pagina rotta
        st.error(f"Si è verificato un errore imprevisto ({type(e).__name__}). "
                 "Riprova; se si ripete, segnala il problema indicando il file usato.")
        return

    st.session_state.pop("scelta_fuori_periodo", None)     # nuova conversione, nuove scelte
    st.session_state.pop("scelta_duplicati", None)
    st.session_state["esito"] = {
        "firma": _firma(provider, ditta_txt, periodo_txt, file),
        "provider": provider, "ditta": ditta, "periodo": periodo, "prep": prep,
    }


def _mostra_esito(esito):
    prep, ditta, periodo = esito["prep"], esito["ditta"], esito["periodo"]
    fuori = prep.fuori_periodo
    gruppi = prep.duplicati

    def calcola(includi, tieni):
        # finché una scelta non è fatta si simula "includi / tieni", solo per mostrare i totali
        return genera(prep, ditta, periodo,
                      includi_fuori_periodo=True if includi is None else includi,
                      tieni_duplicati=True if tieni is None else tieni)

    st.subheader("4. Controlla l'esito")

    # --- scelta 1: righe con la data fuori periodo --------------------------------------
    scelta_fp = None
    if fuori:
        st.warning(
            f"**Ho trovato {_righe(len(fuori), 'riga con una data che non è', 'righe con una data che non è')} "
            f"di {periodo_a_testo(periodo)}.** Qui sotto le vedi tutte."
        )
        st.dataframe(tabella_movimenti(fuori, con_motivo=True), hide_index=True)
        scelta_fp = st.radio(
            "Vuoi includerle nel file?", [SCELTA_INCLUDI, SCELTA_ESCLUDI], index=None,
            key="scelta_fuori_periodo",
            help="Finché non scegli, il pulsante di download resta disattivato.",
        )
    includi = None if (fuori and scelta_fp is None) else (scelta_fp != SCELTA_ESCLUDI)

    # --- scelta 2: righe ripetute ---------------------------------------------------------
    scelta_dup = None
    if gruppi:
        n_extra = sum(g.volte - 1 for g in gruppi)
        st.warning(
            f"**{'C’è 1 riga ripetuta' if len(gruppi) == 1 else f'Ci sono {len(gruppi)} righe ripetute'}** "
            f"(identiche in tutte le colonne del file): in tutto "
            f"{_righe(n_extra, 'copia in più', 'copie in più')}."
        )
        for g in gruppi[:5]:
            st.write("• " + messaggio_duplicato(g))
        if len(gruppi) > 5:
            st.write(f"• …e altre {len(gruppi) - 5}. L'elenco completo è qui sotto.")
        st.dataframe(tabella_duplicati(prep), hide_index=True)
        scelta_dup = st.radio(
            "Vuoi tenere le copie o toglierle?", [SCELTA_TIENI, SCELTA_TOGLI], index=None,
            key="scelta_duplicati",
            help="Togliendole, di ogni riga ripetuta resta una sola copia (la prima). "
                 "Finché non scegli, il pulsante di download resta disattivato.",
        )
    tieni = None if (gruppi and scelta_dup is None) else (scelta_dup != SCELTA_TOGLI)

    # --- totali a confronto per le scelte ancora aperte ------------------------------------
    if fuori:
        st.caption(
            f"Date fuori periodo, totale importi con queste righe: "
            f"**{formatta_euro(calcola(True, tieni).totale_cent)} €** · "
            f"senza: **{formatta_euro(calcola(False, tieni).totale_cent)} €**")
    if gruppi:
        st.caption(
            f"Righe ripetute, totale importi tenendo le copie: "
            f"**{formatta_euro(calcola(includi, True).totale_cent)} €** · "
            f"togliendole: **{formatta_euro(calcola(includi, False).totale_cent)} €**")

    risultato = calcola(includi, tieni)
    in_attesa = includi is None or tieni is None

    # --- riepilogo ------------------------------------------------------------------------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Righe lette", prep.righe_lette)
    c2.metric("Record nel file", len(risultato.righe_output))
    c3.metric("Totale importi", f"{formatta_euro(risultato.totale_cent)} €")
    c4.metric("Righe scartate", len(risultato.scarti))

    # --- scarti ---------------------------------------------------------------------------
    if risultato.scarti:
        n_scarti = len(risultato.scarti)
        if n_scarti == 1:
            st.error("**1 riga non è stata convertita e NON è nel file.** "
                     "Controllala prima di scaricare.")
        else:
            st.error(f"**{n_scarti} righe non sono state convertite e NON sono nel file.** "
                     "Controllale prima di scaricare.")
        st.dataframe(tabella_scarti(risultato), hide_index=True)

    # --- negativi -------------------------------------------------------------------------
    if prep.negativi:
        st.warning(
            f"**{_righe(len(prep.negativi), 'riga ha', 'righe hanno')} un importo negativo.** Il tracciato non "
            "ammette importi negativi: vengono sottratte dal totale del dipendente per quella "
            "voce, e se il totale resta negativo il record non viene creato (lo vedi tra le "
            "righe scartate)."
        )
        st.dataframe(tabella_movimenti(prep.negativi), hide_index=True)

    # --- avvisi ---------------------------------------------------------------------------
    if risultato.avvisi:
        with st.expander(f"Avvisi ({len(risultato.avvisi)})", expanded=True):
            for avviso in risultato.avvisi:
                st.write(f"• {avviso}")

    if not conta_cose_da_controllare(prep, risultato) and not risultato.avvisi:
        st.success("Conversione completata senza anomalie.")

    # --- download -------------------------------------------------------------------------
    st.subheader("5. Scarica")
    n = len(risultato.righe_output)
    if in_attesa:
        mancanti = []
        if includi is None:
            mancanti.append("le righe fuori periodo")
        if tieni is None:
            mancanti.append("le righe ripetute")
        st.info(f"Scegli cosa fare con {' e con '.join(mancanti)} per attivare il download.")
    elif n == 0:
        st.error("Non c'è nessun record da scaricare: tutte le righe sono state scartate. "
                 "Controlla di aver scelto il provider e la ditta giusti.")

    if risultato.scarti:
        etichetta = (f"Scarica VOCI comunque ({_righe(n, 'record', 'record')}, "
                     f"{_righe(len(risultato.scarti), 'riga scartata', 'righe scartate')})")
    else:
        etichetta = f"Scarica VOCI ({n} record)"
    st.download_button(
        etichetta, data=risultato.testo_output().encode("ascii"),
        file_name=nome_file_output(ditta, periodo), mime="text/plain", type="primary",
        disabled=(in_attesa or n == 0),
    )

    if risultato.scarti or prep.negativi or fuori or gruppi or risultato.avvisi:
        st.download_button(
            "Scarica il log delle anomalie",
            data=log_anomalie(esito["provider"], ditta, periodo, prep, risultato, includi, tieni),
            file_name=f"LOG_{ditta}_{periodo}.txt", mime="text/plain",
        )


def main():
    st.set_page_config(page_title="Convertitore welfare", page_icon="🧾", layout="centered")
    st.title("Convertitore welfare")
    st.write("Trasforma il report del provider nel file voci da importare nelle paghe. "
             "Compila i passi qui sotto, dall'alto verso il basso.")

    provider_disponibili = elenca_provider()
    if not provider_disponibili:
        st.error("Non trovo nessuna configurazione dei provider nella cartella «configs».")
        return

    st.subheader("1. Di quale cedolino si tratta?")
    provider = st.selectbox("Provider", list(provider_disponibili))
    col_ditta, col_periodo = st.columns(2)
    ditta_txt = col_ditta.text_input("Codice ditta", placeholder="ad esempio 4012", max_chars=6)
    periodo_txt = col_periodo.text_input(
        "Periodo del cedolino (AAAAMM)", value=periodo_predefinito(), max_chars=6,
        help="Anno e mese del cedolino, ad esempio 202609 per settembre 2026.")

    st.subheader("2. Carica il file del provider")
    file = st.file_uploader("Scegli il file", type=["xlsx", "xls", "csv"],
                            help="Il file resta sul server solo il tempo della conversione.")

    st.subheader("3. Converti")
    if st.button("Converti", type="primary"):
        _converti(provider, provider_disponibili[provider], ditta_txt, periodo_txt, file)

    esito = st.session_state.get("esito")
    if not esito:
        return
    if esito["firma"] != _firma(provider, ditta_txt, periodo_txt, file):
        st.info("Hai cambiato qualcosa dopo l'ultima conversione: premi di nuovo «Converti» "
                "per aggiornare l'esito.")
        return
    _mostra_esito(esito)


if __name__ == "__main__":
    main()
