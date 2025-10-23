# tests/conftest.py
import uuid
import pytest
from typing import Iterator, Optional, Dict, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool  # <-- clave para compartir la conexión en memoria

# Importa modelos para registrar todas las tablas ANTES de create_all
from src.domain import models as _models  # noqa: F401  <-- asegura el registro de las clases
from src.domain.models import Base
from src.errors import NotFoundError, ConflictError
from src.dependencies import AuditContext

# Router real
from src.routes.logistica import router as logistica_router

# Servicio a parchear (para inyectar MsClient fake)
from src.services import logistica_service


# -----------------------------
# DB SQLite en memoria (aislada por test, 1 conexión compartida)
# -----------------------------
@pytest.fixture()
def engine_sqlite():
    """
    Crea un engine SQLite en memoria *por test*,
    usando StaticPool para que *todas las sesiones del test*
    compartan la MISMA conexión (y por tanto la misma BD en memoria).
    """
    engine = create_engine(
        "sqlite+pysqlite://",                # ¡sin :memory: explícito!
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,                # <- reutiliza siempre la misma conexión
        future=True,
    )
    # Asegúrate de que todas las tablas estén registradas en Base.metadata
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def db_session(engine_sqlite) -> Iterator:
    """
    Sesión ligada al engine del test.
    """
    SessionLocal = sessionmaker(
        bind=engine_sqlite,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    with SessionLocal() as s:
        yield s
        # No es necesario rollback aquí; la BD se destruye al final del test


# -----------------------------
# MsClient Fake (sin red)
# -----------------------------
class FakeMsClient:
    """
    Fake muy simple. Usa 'fixtures' para decidir respuestas.

    Claves soportadas en fixtures:
      - ('pedidos', <params_tuple>) -> list[dict]  # respuesta exacta para GET .../v1/pedidos con esos params
      - 'pedidos_default' -> list[dict]            # fallback si no hay match por params
      - 'pedidos' -> list[dict]                    # fallback más general
      - 'usuarios' -> dict[int, {"direccion"|"address": str|None, "ciudad"|"city": str|None}]
      - 'marcar_falla' -> set[str]                 # IDs que fallan en POST .../v1/pedidos/{id}/marcar-despachado
    """
    def __init__(self, x_country: str, fixtures: Optional[Dict[str, Any]] = None):
        self.x_country = x_country
        self.fixtures = fixtures or {}

    # ---------------- path matching helpers ----------------
    def _is_pedidos_path(self, path: str) -> bool:
        p = path.lower()
        return p.endswith("/v1/pedidos") or p == "/v1/pedidos" or p == "v1/pedidos"

    def _is_usuario_detalle_path(self, path: str) -> bool:
        return "/v1/usuarios/usuario/" in path.lower()

    def _extract_cliente_id(self, path: str) -> int:
        tail = path.rsplit("/", 1)[-1]
        tail = tail.split("?", 1)[0]
        return int(tail)

    # ---------------- HTTP methods ----------------
    def get(self, path: str, params: Optional[Dict[str, Any]] = None):
        if self._is_pedidos_path(path):
            # intenta match exacto por params (ordenados)
            key = ("pedidos", tuple(sorted((params or {}).items())))
            if key in self.fixtures:
                return self.fixtures[key]
            # fallbacks
            if "pedidos_default" in self.fixtures:
                return self.fixtures["pedidos_default"]
            return self.fixtures.get("pedidos", [])

        if self._is_usuario_detalle_path(path):
            cid = self._extract_cliente_id(path)
            raw = self.fixtures.get("usuarios", {}).get(cid, {})
            # tolera tanto {'direccion','ciudad'} como {'address','city'}
            return {
                "direccion": raw.get("direccion") or raw.get("address"),
                "ciudad": raw.get("ciudad") or raw.get("city"),
            }

        raise ValueError(f"[FakeMsClient] GET no mockeado: {path}")

    def post(self, path: str, json=None, params=None):
        p = path.lower()
        if p.endswith("/marcar-despachado") and "/v1/pedidos/" in p:
            # .../v1/pedidos/{id}/marcar-despachado
            pid = path.split("/")[3]
            fails = self.fixtures.get("marcar_falla", set())
            if pid in fails:
                raise RuntimeError("Fallo intencional marcar-despachado")
            return {"status": "ok"}
        raise ValueError(f"[FakeMsClient] POST no mockeado: {path}")



@pytest.fixture()
def ms_fixtures() -> Dict[str, Any]:
    return {}


@pytest.fixture()
def patch_msclient(monkeypatch, ms_fixtures):
    """
    Reemplaza MsClient dentro del servicio por el FakeMsClient.
    """
    def _factory(x_country: str):
        return FakeMsClient(x_country=x_country, fixtures=ms_fixtures)

    monkeypatch.setattr(logistica_service, "MsClient", lambda x_country: _factory(x_country))
    return ms_fixtures


# -----------------------------
# App FastAPI de integración
# -----------------------------
@pytest.fixture()
def test_app(db_session, monkeypatch) -> TestClient:
    """
    Crea una app de pruebas que usa:
      - el router real de logística
      - handlers de NotFound/Conflict
      - overrides de get_session y audit_context
    La sesión inyectada (db_session) está ligada al engine con StaticPool,
    por lo que las tablas creadas son visibles en cada request del test.
    """
    app = FastAPI(title="ms-logistica (tests)")

    @app.exception_handler(NotFoundError)
    async def _nf(_: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def _cf(_: Request, exc: ConflictError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    # Overrides de dependencias del router
    import src.routes.logistica as logistica_route_mod

    def _override_get_session():
        # YIELD la *misma* sesión ligada al engine del test
        yield db_session

    def _override_audit_context(_: Request = None):
        return AuditContext(
            request_id=uuid.uuid4().hex,
            country="co",
            user_id=None,
            ip="127.0.0.1",
        )

    app.dependency_overrides[logistica_route_mod.get_session] = _override_get_session
    app.dependency_overrides[logistica_route_mod.audit_context] = _override_audit_context

    app.include_router(logistica_router)

    return TestClient(app)
