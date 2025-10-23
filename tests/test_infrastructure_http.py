import pytest
from src.infrastructure.http import MsClient


class DummyResponse:
    def __init__(self, status_code=200, json_body=None, text="OK", url=""):
        self.status_code = status_code
        self._json = {} if json_body is None else json_body
        self.text = text
        self.url = url
        self.request = type("R", (), {"method": "GET"})()

    @property
    def content(self):
        # Simula contenido para .json()
        return b"{}" if self._json is not None else b""

    def json(self):
        return self._json


def test_msclient_get_ok(monkeypatch):
    sent = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        sent["url"] = url
        sent["headers"] = headers
        sent["params"] = params
        r = DummyResponse(200, {"pong": True}, url=url)
        r.request = type("R", (), {"method": "GET"})()
        return r

    # setea base URL del gateway y parchea requests.get
    monkeypatch.setattr("src.config.settings.GATEWAY_BASE_URL", "https://api.example.com", raising=False)
    monkeypatch.setattr("requests.get", fake_get, raising=False)

    c = MsClient(x_country="co")
    out = c.get("/v1/ping", params={"a": "1"})
    assert out == {"pong": True}
    assert sent["url"] == "https://api.example.com/v1/ping"
    assert sent["headers"]["X-Country"] == "co"
    assert sent["headers"]["Content-Type"] == "application/json"
    assert sent["params"] == {"a": "1"}


def test_msclient_post_error_levanta(monkeypatch):
    def fake_post(url, headers=None, json=None, params=None, timeout=None):
        r = DummyResponse(500, {"error": "boom"}, text="Internal Server Error", url=url)
        r.request = type("R", (), {"method": "POST"})()
        return r

    monkeypatch.setattr("src.config.settings.GATEWAY_BASE_URL", "https://gw.example", raising=False)
    monkeypatch.setattr("requests.post", fake_post, raising=False)

    c = MsClient(x_country="pe")
    with pytest.raises(Exception) as exc:
        c.post("/v1/pedidos/ID/marcar-despachado", json={})
    assert "HTTP 500 calling POST https://gw.example/v1/pedidos/ID/marcar-despachado" in str(exc.value)