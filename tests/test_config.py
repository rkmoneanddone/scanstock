import json

import pytest

from scanstock.config import load_instruments


def test_instrument_chunks_are_combined(tmp_path):
    chunk_root = tmp_path / "config" / "instruments"
    chunk_root.mkdir(parents=True)
    row = lambda symbol, security_id: {
        "symbol": symbol, "security_id": security_id, "display_name": symbol,
        "exchange_segment": "NSE_EQ", "instrument_type": "EQUITY",
    }
    (chunk_root / "01.json").write_text(json.dumps([row("ONE", "1")]), encoding="utf-8")
    (chunk_root / "02.json").write_text(json.dumps([row("TWO", "2")]), encoding="utf-8")
    assert list(load_instruments(tmp_path)) == ["ONE", "TWO"]


def test_duplicate_symbols_across_chunks_are_rejected(tmp_path):
    chunk_root = tmp_path / "config" / "instruments"
    chunk_root.mkdir(parents=True)
    row = [{"symbol":"ONE","security_id":"1","display_name":"One","exchange_segment":"NSE_EQ","instrument_type":"EQUITY"}]
    for name in ("01.json", "02.json"):
        (chunk_root / name).write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate symbols"):
        load_instruments(tmp_path)
