import pytest
from src.infrastructure.http import MsClient
from src.infrastructure.infrastructure import publish_event
import json
from uuid import uuid4


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


def test_publish_event_ok(monkeypatch):
    import src.infrastructure.infrastructure as infra

    class DummyFuture:
        def __init__(self):
            self.called = False
        def result(self, timeout=None):
            self.called = True

    class DummyPublisher:
        def __init__(self):
            self.calls = []
        def publish(self, topic, payload):
            self.calls.append((topic, payload))
            return DummyFuture()

    dummy = DummyPublisher()

    # 👇 Ahora mockeamos get_publisher, NO el publisher global
    monkeypatch.setattr(infra, "get_publisher", lambda: dummy)

    topic = f"projects/test/topics/{uuid4()}"
    data = {"foo": "bar", "n": 1}

    publish_event(data, topic)

    assert len(dummy.calls) == 1
    sent_topic, sent_payload = dummy.calls[0]
    assert sent_topic == topic
    decoded = json.loads(sent_payload.decode("utf-8"))
    assert decoded == data


def test_publish_event_propagates_error(monkeypatch):
    import src.infrastructure.infrastructure as infra

    class BoomPublisher:
        def publish(self, topic, payload):
            raise RuntimeError("pubsub error")

    monkeypatch.setattr(infra, "get_publisher", lambda: BoomPublisher())

    with pytest.raises(RuntimeError):
        publish_event({"x": 1}, "projects/test/topics/x")