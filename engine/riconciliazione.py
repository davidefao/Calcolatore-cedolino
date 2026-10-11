"""Riconciliazione: dal report del provider ai codici del gestionale.

- Anagrafica: trova il codice dipendente (sempre dentro la ditta indicata).
- CatalogoVoci: trova il codice voce a partire dal trattamento fiscale.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from engine.parsing import chiave_codice, chiave_nome, normalizza_trattamento
from engine.reader import leggi_file


class ErroreRiconciliazione(Exception):
    """Dipendente o voce non trovati (o ambigui). Il messaggio va nel log."""


# ================================================================ dipendenti

@dataclass(frozen=True)
class Dipendente:
    codice: str            # codice gestionale (CodAnagraficoLav)
    nome: str
    codice_fiscale: str


class Anagrafica:
    """Dipendenti di UNA ditta, con indici per codice fiscale, codice e nome."""

    TIPI = ("codice_fiscale", "codice", "nome")

    def __init__(self, dipendenti: list):
        self.dipendenti = dipendenti
        self._indici = {t: defaultdict(set) for t in self.TIPI}
        for d in dipendenti:
            self._indici["codice_fiscale"][d.codice_fiscale.strip().upper()].add(d)
            self._indici["codice"][chiave_codice(d.codice)].add(d)
            self._indici["nome"][chiave_nome(d.nome)].add(d)

    def trova(self, tipo: str, valore: str, ditta: str = "") -> Dipendente:
        if tipo not in self.TIPI:
            raise ErroreRiconciliazione(f"Tipo di chiave dipendente sconosciuto: {tipo}")
        if tipo == "codice_fiscale":
            chiave = (valore or "").strip().upper()
        elif tipo == "codice":
            chiave = chiave_codice(valore)
        else:
            chiave = chiave_nome(valore)

        if not chiave:
            raise ErroreRiconciliazione("chiave del dipendente vuota")
        trovati = self._indici[tipo].get(chiave, set())
        if not trovati:
            raise ErroreRiconciliazione(f"dipendente non presente nella ditta {ditta}".strip())
        if len(trovati) > 1:
            codici = ", ".join(sorted(d.codice for d in trovati))
            raise ErroreRiconciliazione(
                f"dipendente ambiguo nella ditta {ditta}: corrisponde ai codici {codici}"
            )
        return next(iter(trovati))


def carica_anagrafica(contenuto: bytes, ditta: int) -> Anagrafica:
    """Legge Lista_Dipendenti e tiene solo la ditta richiesta, senza doppioni."""
    tabella = leggi_file(contenuto, "Lista_Dipendenti.csv", {"separatore": ","})
    ditta_txt = str(int(ditta))
    visti, dipendenti = set(), []
    for r in tabella.righe:
        v = r.valori
        if v["Codice Ditta"].strip() != ditta_txt:
            continue
        d = Dipendente(
            codice=v["CodAnagraficoLav"].strip(),
            nome=v["Nome Dipendente"].strip(),
            codice_fiscale=v["CodiceFiscale"].strip().upper(),
        )
        if d not in visti:                      # righe duplicate esatte
            visti.add(d)
            dipendenti.append(d)
    return Anagrafica(dipendenti)


# ================================================================ voci

@dataclass(frozen=True)
class RigaCodice:
    trattamento: str
    codice: str
    sottocategoria: str


class CatalogoVoci:
    """Trasforma un trattamento fiscale nel codice voce del gestionale.

    Regole (in ordine):
      0. eccezioni dichiarate nella configurazione del provider;
      1. testo identico nel file dei codici;
      2. altrimenti testo normalizzato (match approssimato, segnalato);
      in entrambi i casi:
         - se il report indica una sottocategoria che esiste, si usa quella;
         - se non esiste, si usa il caso base (riga senza sottocategoria);
         - se non c'è il caso base, o i casi base sono discordanti: errore.
    """

    def __init__(self, righe: list):
        self.righe = righe
        self._esatto = defaultdict(list)
        self._normalizzato = defaultdict(list)
        for r in righe:
            self._esatto[r.trattamento.strip()].append(r)
            self._normalizzato[normalizza_trattamento(r.trattamento)].append(r)

    @staticmethod
    def _scegli(candidate: list, sottocategoria: str):
        """Restituisce (codice, riga_esempio) oppure None se non risolvibile."""
        if sottocategoria:
            con_sub = [r for r in candidate
                       if r.sottocategoria.strip().casefold() == sottocategoria.strip().casefold()]
            if con_sub:
                return CatalogoVoci._unico(con_sub, f"sottocategoria «{sottocategoria}»")
        base = [r for r in candidate if not r.sottocategoria.strip()]
        if base:
            return CatalogoVoci._unico(base, "caso base")
        return None

    @staticmethod
    def _unico(righe: list, descrizione: str):
        codici = sorted({r.codice for r in righe})
        if len(codici) > 1:
            raise ErroreRiconciliazione(
                f"voce ambigua ({descrizione}): i codici possibili sono {', '.join(codici)}. "
                "Indica la voce corretta tra le eccezioni della configurazione."
            )
        return codici[0], righe[0]

    def trova(self, trattamento: str, sottocategoria: str = "", eccezioni=()):
        """Restituisce (codice_voce, avviso) dove avviso è None se il match è esatto."""
        trattamento = (trattamento or "").strip()
        sottocategoria = (sottocategoria or "").strip()
        if not trattamento:
            raise ErroreRiconciliazione("trattamento fiscale vuoto")

        for e in eccezioni:                                          # 0. eccezioni
            if (e["trattamento"].strip() == trattamento
                    and e.get("sottocategoria", "").strip().casefold() == sottocategoria.casefold()):
                return str(e["voce"]), None

        scelta = self._scegli(self._esatto.get(trattamento, []), sottocategoria)   # 1.
        if scelta:
            return scelta[0], None

        candidate = self._normalizzato.get(normalizza_trattamento(trattamento), [])  # 2.
        scelta = self._scegli(candidate, sottocategoria)
        if scelta:
            codice, esempio = scelta
            return codice, (
                f"«{trattamento}» non è presente identico nei codici: "
                f"usata la voce {codice} per somiglianza con «{esempio.trattamento}»"
            )

        if sottocategoria:
            raise ErroreRiconciliazione(
                f"trattamento «{trattamento}» (sottocategoria «{sottocategoria}») "
                "senza voce corrispondente nei codici"
            )
        raise ErroreRiconciliazione(f"trattamento «{trattamento}» non presente nei codici")


def carica_catalogo(contenuto: bytes) -> CatalogoVoci:
    """Legge Codici_Welfare_Voci_Payroll (virgole tra virgolette incluse)."""
    tabella = leggi_file(contenuto, "Codici_Welfare_Voci_Payroll.csv", {"separatore": ","})
    righe = [
        RigaCodice(
            trattamento=r.valori["Trattamento"],
            codice=r.valori["Codice"].strip(),
            sottocategoria=r.valori.get("Sottocategoria", ""),
        )
        for r in tabella.righe
    ]
    return CatalogoVoci(righe)
