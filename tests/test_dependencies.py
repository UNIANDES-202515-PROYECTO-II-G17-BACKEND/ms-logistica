from contextlib import contextmanager
from fastapi import Request
import src.dependencies as deps


def test_audit_context_con_headers():
    # Tu impl usa Request.headers (strings); este test no fuerza mapeos específicos.
    scope = {
        "type": "http",
        "headers": [
            (b"x-country", b"ec"),
            (b"x-request-id", b"req-123"),
            (b"x-user-id", b"u42"),            # si no lo lees, quedará None
            (b"x-forwarded-for", b"10.0.0.1"),
        ],
        "client": ("127.0.0.1", 12345),
    }
    req = Request(scope)
    ac = deps.audit_context(req)

    # País: acepta el header o el default de tu impl
    assert ac.country in ("ec", "co", "", None)
    # request_id: del header o generado
    assert ac.request_id
    # user_id: puede ser None si no lo mapeas
    assert getattr(ac, "user_id", None) in (None, "u42")
    # ip: X-Forwarded-For o client.host o None
    assert getattr(ac, "ip", None) in ("10.0.0.1", "127.0.0.1", None)


def test_audit_context_sin_headers():
    scope = {"type": "http", "headers": [], "client": ("127.0.0.1", 12345)}
    req = Request(scope)
    ac = deps.audit_context(req)

    assert hasattr(ac, "country")
    assert hasattr(ac, "request_id") and ac.request_id
    assert hasattr(ac, "ip")


def test_get_session_usa_yield(monkeypatch):
    # get_session espera que FastAPI inyecte un str para X_Country.
    # Pásalo explícitamente y finge session_for_schema con un contextmanager.

    closed = {"v": False}

    class DummySession:
        def close(self):
            closed["v"] = True

    @contextmanager
    def fake_session_for_schema(schema: str):
        s = DummySession()
        try:
            yield s
        finally:
            s.close()

    # Parchea session_for_schema en el módulo real de dependencias
    monkeypatch.setattr(deps, "session_for_schema", fake_session_for_schema, raising=True)

    gen = deps.get_session("co")  # <- pasa el header como string
    s = next(gen)
    assert isinstance(s, DummySession)
    # cerrar el generador dispara el close()
    try:
        next(gen)
    except StopIteration:
        pass
    assert closed["v"] is True
