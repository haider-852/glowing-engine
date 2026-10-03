from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"ok": True}


def test_parse():
    body = client.get("/api/citations/parse", params={"q": "see (1973) 4 S.C.C. 225 and AIR 1948 SC 1"}).json()
    first, second = body["citations"]
    assert first["canonical"] == "(1973) 4 SCC 225" and first["issues"] == []
    assert second["canonical"] == "AIR 1948 SC 1" and second["issues"]


def test_resolve():
    body = client.get("/api/resolve", params={"q": "Shah Bano"}).json()
    assert body["status"] == "resolved"
    assert body["candidates"][0]["id"] == "shah-bano-1985"
    assert "(1985) 2 SCC 556" in body["candidates"][0]["citations"]


def test_lookup_says_could_not_verify_without_sources():
    body = client.get("/api/lookup", params={"q": "Shah Bano"}).json()
    assert body["resolution"]["status"] == "resolved"
    assert body["verification"]["status"] == "could_not_verify"
    assert "not legal advice" in body["disclaimer"]


def test_lookup_fake_case():
    body = client.get("/api/lookup", params={"q": "Sharma v. State of Kerala"}).json()
    assert body["resolution"]["status"] != "resolved"
    assert body["verification"]["status"] == "could_not_verify"


def test_rejects_empty_and_huge_queries():
    assert client.get("/api/resolve", params={"q": ""}).status_code == 422
    assert client.get("/api/resolve", params={"q": "x" * 501}).status_code == 422
