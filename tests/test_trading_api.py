"""API validation tests without optional HTTP test-client dependencies."""
import pytest
from fastapi import HTTPException
from scanstock.web import trading_research

def test_research_api_rejects_invalid_symbol():
    with pytest.raises(HTTPException) as exc:
        trading_research("INVALID SYMBOL", split_at="2025-01-01")
    assert exc.value.status_code == 422

def test_research_api_requires_valid_date():
    with pytest.raises(HTTPException) as exc:
        trading_research("ABC", split_at="2025-99-99")
    assert exc.value.status_code == 422
