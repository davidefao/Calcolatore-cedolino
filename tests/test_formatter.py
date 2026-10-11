from decimal import Decimal
import pytest
from engine.formatter import formatta_record, euro_a_centesimi


def test_esempio_del_brief():
    riga = formatta_record(4012, "4", "371", 2244, "202609")
    assert riga == "0040124     371 0000000000002244202609"
    assert len(riga) == 38


def test_centesimi_senza_float():
    assert euro_a_centesimi(Decimal("25.73")) == 2573
    assert euro_a_centesimi(Decimal("0.1") + Decimal("0.2")) == 30


def test_codice_dipendente_troppo_lungo():
    with pytest.raises(ValueError):
        formatta_record(4012, "1234567", "371", 100, "202609")