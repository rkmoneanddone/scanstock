from fastapi.testclient import TestClient
from scanstock.web import app

def test_research_api_rejects_invalid_symbol():
    with TestClient(app) as client:
        response = client.get("/api/trading/research/INVALID%20SYMBOL")
    assert response.status_code == 422

def test_research_api_requires_valid_date():
    with TestClient(app) as client:
        response = client.get("/api/trading/research/ABC?split_at=2025-99-99")
    assert response.status_code == 422
