# tests/test_services_logistica.py
import uuid
import pytest
from datetime import date

from src.services import logistica_service
from src.domain.models import RutaEntrega, Parada, ParadaPedido, RutaEstado, ParadaEstado
from src.errors import NotFoundError, ConflictError

# ---------- helpers ----------
def _pedido(pid: uuid.UUID, cliente_id: int):
    return {"id": str(pid), "cliente_id": cliente_id, "tipo": "VENTA", "estado": "APROBADO"}

# ---------- tests ----------

def test_generar_ruta_sin_pedidos_da_404(db_session, patch_msclient):
    patch_msclient["pedidos_default"] = []  # ms-pedidos retorna lista vacía
    with pytest.raises(NotFoundError) as e:
        logistica_service.generar_ruta(
            db_session, date(2025, 10, 24),
            audit_context := type("A",(object,),{"country":"co"})(),
            tipo="VENTA",
        )
    assert "No hay ventas para generar ruta de entrega en la fecha seleccionada." in str(e.value)

def test_generar_ruta_agrupa_por_cliente_direccion_ciudad(db_session, patch_msclient):
    # Dos pedidos del mismo cliente -> una sola parada con 2 vínculos
    pid1, pid2 = uuid.uuid4(), uuid.uuid4()
    params = tuple(sorted([("tipo","VENTA"),("estado","APROBADO"),("fecha_compromiso","2025-10-24"),("limit","200"),("offset","0")]))
    patch_msclient[("pedidos", params)] = [_pedido(pid1, 101), _pedido(pid2, 101)]
    patch_msclient["usuarios"] = {101: {"direccion": "Calle 123 #45-67", "ciudad":"Bogotá"}}

    ruta = logistica_service.generar_ruta(
        db_session, date(2025, 10, 24),
        audit_context := type("A",(object,),{"country":"co"})(),
        tipo="VENTA",
    )

    db_session.refresh(ruta)
    assert ruta.estado == RutaEstado.PLANEADA
    assert len(ruta.paradas) == 1
    p = ruta.paradas[0]
    assert p.cliente_id == 101
    assert p.direccion == "Calle 123 #45-67"
    assert p.ciudad == "Bogotá"
    assert len(p.pedidos) == 2
    assert set(v.pedido_id for v in p.pedidos) == {pid1, pid2}

def test_generar_ruta_no_duplica_fecha(db_session, patch_msclient):
    pid = uuid.uuid4()
    params = tuple(sorted([("tipo","VENTA"),("estado","APROBADO"),("fecha_compromiso","2025-10-24"),("limit","200"),("offset","0")]))
    patch_msclient[("pedidos", params)] = [_pedido(pid, 201)]
    patch_msclient["usuarios"] = {201: {"direccion": "Calle 1", "ciudad":"Cali"}}

    audit = type("A",(object,),{"country":"co"})()
    r1 = logistica_service.generar_ruta(db_session, date(2025,10,24), audit, tipo="VENTA")
    with pytest.raises(ConflictError):
        logistica_service.generar_ruta(db_session, date(2025,10,24), audit, tipo="VENTA")

def test_actualizar_estado_parada_y_finaliza_ruta(db_session, patch_msclient):
    # Prepara una ruta con 2 paradas y un pedido cada una (usuarios mock)
    pid1, pid2 = uuid.uuid4(), uuid.uuid4()
    params = tuple(sorted([("tipo","VENTA"),("estado","APROBADO"),("fecha_compromiso","2025-10-24"),("limit","200"),("offset","0")]))
    patch_msclient[("pedidos", params)] = [_pedido(pid1, 1), _pedido(pid2, 2)]
    patch_msclient["usuarios"] = {
        1: {"direccion":"DirA","ciudad":"Bogotá"},
        2: {"direccion":"DirB","ciudad":"Bogotá"},
    }

    audit = type("A",(object,),{"country":"co"})()
    ruta = logistica_service.generar_ruta(db_session, date(2025,10,24), audit, tipo="VENTA")
    db_session.refresh(ruta)
    p1, p2 = sorted(ruta.paradas, key=lambda x: x.orden)

    # Entrego primera -> ruta pasa a EN_RUTA
    pa1 = logistica_service.actualizar_estado_parada(db_session, p1.id, ParadaEstado.ENTREGADA)
    assert pa1.estado == ParadaEstado.ENTREGADA
    db_session.refresh(ruta)
    assert ruta.estado == RutaEstado.EN_RUTA

    # Entrego segunda -> ruta FINALIZADA
    pa2 = logistica_service.actualizar_estado_parada(db_session, p2.id, ParadaEstado.ENTREGADA)
    db_session.refresh(ruta)
    assert ruta.estado == RutaEstado.FINALIZADA
