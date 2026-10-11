from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "data"
CONFIGS = Path(__file__).resolve().parent.parent / "configs"


@pytest.fixture
def dato():
    """Restituisce il percorso di un file in data/ (in qualunque sottocartella)."""
    def _cerca(nome):
        trovati = list(DATA.rglob(nome))
        if not trovati:
            pytest.skip(f"File mancante in data/: {nome}")
        return trovati[0]
    return _cerca
