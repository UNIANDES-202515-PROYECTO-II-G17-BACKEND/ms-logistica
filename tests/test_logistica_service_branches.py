import uuid
import pytest
from datetime import date

from src.services import logistica_service
from src.errors import NotFoundError, ConflictError
from src.domain.models import RutaEstado, ParadaEstado

# ---- helpers ----
class A:  # audit fake
    def __init__(self, country="co"): self.country=country

def _params(fecha="2025-10-24", tipo="VENTA", limit="200", offset="0"):
    return tuple(sorted([("tipo",tipo),("estado","APROBADO"),("fecha_compromiso",fecha),("limit",limit),("offset",offset)]))

# 1) _ms_pedidos_listar_aprobados devuelve dict con 'items'
def test_ms_pedidos_dict_items(db_session, patch_msclient, monkeypatch):
    patch_msclient[("pedidos", _params())] = {"items": [
        {"id": str(uuid.uuid4()), "cliente_id": 99, "tipo":"VENTA","estado":"APROBADO"}
    ]}
    patch_msclient["usuarios"] = {99: {"address":"Calle 1", "city":"Bogotá"}}

    # fuerza MsClient de servicio a usar el fake ya inyectado en conftest
    r = logistica_service.generar_ruta(db_session, date(2025,10,24), A(), tipo="VENTA")
    assert r.estado == RutaEstado.PLANEADA
    assert len(r.paradas) == 1
    # cubrir listar_rutas_por_fecha
    rutas = logistica_service.listar_rutas_por_fecha(db_session, date(2025,10,24))
    assert len(rutas) == 1

# 2) _ms_pedidos_listar_aprobados devuelve tipo inesperado -> []
def test_ms_pedidos_tipo_inesperado_da_404(db_session, patch_msclient):
    patch_msclient[("pedidos", _params())] = 123  # tipo inesperado
    with pytest.raises(NotFoundError):
        logistica_service.generar_ruta(db_session, date(2025,10,24), A(), tipo="VENTA")

# 3) Sin pedidos -> 404 de negocio (mensaje exacto)
def test_generar_ruta_sin_pedidos_404(db_session, patch_msclient):
    patch_msclient[("pedidos", _params())] = []
    with pytest.raises(NotFoundError) as exc:
        logistica_service.generar_ruta(db_session, date(2025,10,24), A(), tipo="VENTA")
    assert "No hay ventas para generar ruta de entrega en la fecha seleccionada" in str(exc.value)

# 4) Conflicto por fecha duplicada
def test_generar_ruta_conflicto_fecha(db_session, patch_msclient):
    pid = str(uuid.uuid4())
    patch_msclient[("pedidos", _params())] = [{"id": pid, "cliente_id": 1, "tipo":"VENTA","estado":"APROBADO"}]
    patch_msclient["usuarios"] = {1: {"address":"Dir A", "city":"Bogotá"}}
    a = A()
    r1 = logistica_service.generar_ruta(db_session, date(2025,10,24), a, tipo="VENTA")
    assert r1.id is not None
    with pytest.raises(ConflictError):
        logistica_service.generar_ruta(db_session, date(2025,10,24), a, tipo="VENTA")

# 5) _ms_pedido_marcar_despachado reintenta y falla
def test_marcar_despachado_reintenta_y_falla(monkeypatch):
    calls = {"n":0}
    class FF:
        def __init__(self, x_country): ...
        def post(self, path, json=None, params=None):
            calls["n"] += 1
            raise RuntimeError("boom")
    monkeypatch.setattr(logistica_service, "MsClient", FF)
    ok = logistica_service._ms_pedido_marcar_despachado(FF("co"), "x-id")
    assert ok is False
    assert calls["n"] == logistica_service.MAX_RETRIES

# 6) actualizar_estado_parada: EN_RUTA → FINALIZADA
def test_actualizar_estado_finaliza(db_session, patch_msclient):
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    patch_msclient[("pedidos", _params())] = [
        {"id": p1, "cliente_id": 10, "tipo":"VENTA","estado":"APROBADO"},
        {"id": p2, "cliente_id": 10, "tipo":"VENTA","estado":"APROBADO"},
    ]
    patch_msclient["usuarios"] = {10: {"address":"Calle X", "city":"Cali"}}

    r = logistica_service.generar_ruta(db_session, date(2025,10,24), A(), tipo="VENTA")
    assert r.estado == RutaEstado.PLANEADA
    pa = r.paradas[0]
    # primera entrega: ruta pasa a EN_RUTA
    pa1 = logistica_service.actualizar_estado_parada(db_session, pa.id, ParadaEstado.ENTREGADA)
    r_ref = db_session.get(type(r), r.id)
    assert r_ref.estado in (RutaEstado.EN_RUTA, RutaEstado.FINALIZADA)
    # marca el resto de pedidos de la misma parada como entregada
    # (si tienes varias paradas, repite para todas)
    for p in r_ref.paradas:
        logistica_service.actualizar_estado_parada(db_session, p.id, ParadaEstado.ENTREGADA)
    r_fin = db_session.get(type(r), r.id)
    assert r_fin.estado == RutaEstado.FINALIZADA
