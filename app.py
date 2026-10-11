"""Convertitore welfare: dal report del provider al file voci per le paghe.

Questa pagina disegna soltanto l'interfaccia: tutta la logica sta in engine/.
"""
import streamlit as st

from engine.converter import ErroreConfigurazione, genera
from engine.parsing import ErroreDato, periodo_a_testo, valida_periodo
from engine.reader import ErroreLettura
from engine.servizio import (ErroreInstallazione, conta_cose_da_controllare, converti_file,
                             elenca_provider, formatta_euro, nome_file_output,
                             periodo_predefinito, tabella_movimenti, tabella_scarti,
                             log_anomalie, valida_ditta)

SCELTA_INCLUDI = "Sì, includile nel file"
SCELTA_ESCLUDI = "No, escludile dal file"


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
    except ErroreInstallazione as e:
        st.error(f"Problema dell'applicazione, non del tuo file. {e}")
        return
    except ErroreConfigurazione as e:
        st.error(f"Il file non corrisponde a quello che mi aspetto da {provider}. {e} "
                 "Controlla di aver scelto il provider giusto.")
        return

    st.session_state.pop("scelta_fuori_periodo", None)     # nuova conversione, nuova scelta
    st.session_state["esito"] = {
        "firma": _firma(provider, ditta_txt, periodo_txt, file),
        "provider": provider, "ditta": ditta, "periodo": periodo, "prep": prep,
    }


def _mostra_esito(esito):
    prep, ditta, periodo = esito["prep"], esito["ditta"], esito["periodo"]
    fuori = prep.fuori_periodo

    ris_con = genera(prep, ditta, periodo, includi_fuori_periodo=True)
    ris_senza = genera(prep, ditta, periodo, includi_fuori_periodo=False)

    st.subheader("4. Controlla l'esito")

    # --- la scelta sulle righe fuori periodo (se ce ne sono) -----------------------------
    scelta = None
    if fuori:
        st.warning(
            f"**Ho trovato {_righe(len(fuori), 'riga con una data che non è', 'righe con una data che non è')} "
            f"di {periodo_a_testo(periodo)}.** Qui sotto le vedi tutte."
        )
        st.dataframe(tabella_movimenti(fuori, con_motivo=True), hide_index=True,
                     use_container_width=True)
        scelta = st.radio(
            "Vuoi includerle nel file?",
            [SCELTA_INCLUDI, SCELTA_ESCLUDI], index=None, key="scelta_fuori_periodo",
            help="Finché non scegli, il pulsante di download resta disattivato.",
        )
        st.caption(
            f"Totale importi con queste righe: **{formatta_euro(ris_con.totale_cent)} €** · "
            f"senza: **{formatta_euro(ris_senza.totale_cent)} €**"
        )

    includi = None if (fuori and scelta is None) else (scelta != SCELTA_ESCLUDI)
    risultato = ris_senza if includi is False else ris_con

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
    if not risultato.righe_output and includi is not None:
        st.error("Non c'è nessun record da scaricare: tutte le righe sono state scartate. "
                 "Controlla di aver scelto il provider e la ditta giusti.")
    elif includi is None:
        st.info("Scegli se includere le righe fuori periodo per attivare il download.")

    n = len(risultato.righe_output)
    if risultato.scarti:
        etichetta = (f"Scarica VOCI comunque ({_righe(n, 'record', 'record')}, "
                     f"{_righe(len(risultato.scarti), 'riga scartata', 'righe scartate')})")
    else:
        etichetta = f"Scarica VOCI ({n} record)"
    st.download_button(
        etichetta, data=risultato.testo_output().encode("ascii"),
        file_name=nome_file_output(ditta, periodo), mime="text/plain", type="primary",
        disabled=(includi is None or n == 0),
    )

    if risultato.scarti or prep.negativi or fuori or risultato.avvisi:
        st.download_button(
            "Scarica il log delle anomalie",
            data=log_anomalie(esito["provider"], ditta, periodo, prep, risultato, includi),
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
