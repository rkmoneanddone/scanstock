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

def test_split_date_query_pattern_accepts_iso_date():
    """Direct function tests bypass FastAPI's query validation."""
    import inspect
    import re
    from scanstock.web import trading_research
    query = inspect.signature(trading_research).parameters["split_at"].default
    pattern = next(meta.pattern for meta in query.metadata if getattr(meta, "pattern", None))
    assert re.fullmatch(pattern, "2025-01-01")
    assert not re.fullmatch(pattern, "not-a-date")
