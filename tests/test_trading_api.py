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
    """Inspect FastAPI route metadata; direct function calls bypass query validation."""
    import re
    from scanstock.web import app
    route = next(route for route in app.routes if getattr(route, "path", "") == "/api/trading/research/{symbol}")
    parameter = next(field for field in route.dependant.query_params if field.name == "split_at")
    pattern = parameter.field_info.metadata[0].pattern
    assert re.fullmatch(pattern, "2025-01-01")
    assert not re.fullmatch(pattern, "not-a-date")
