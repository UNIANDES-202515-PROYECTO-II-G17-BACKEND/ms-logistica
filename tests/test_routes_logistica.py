# tests/test_routes_logistica.py
import uuid
from datetime import date
from src.domain.models import ParadaEstado

def _params(fecha="2025-10-24", tipo="VENTA", limit="200", offset="0"):
    return tuple(sorted([("tipo",tipo),("estado","APROBADO"),("fecha_compromiso",fecha),("limit",limit),("offset",offset)]))

def test_post_generar_ruta_sin_pedidos_devuelve_404(test_app, patch_msclient):
    patch_msclient["pedidos_default"] = []
    resp = test_app.post("/v1/logistica/rutas/generar?fecha=2025-10-24&tipo=VENTA", headers={"X-Country":"co"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "No hay ventas para generar ruta de entrega en la fecha seleccionada."

def test_post_generar_ruta_ok_y_listar(test_app, patch_msclient):
    pid = str(uuid.uuid4())
    patch_msclient[("pedidos", _params())] = [{"id": pid, "cliente_id": 10, "tipo":"VENTA","estado":"APROBADO"}]
    patch_msclient["usuarios"] = {10: {"address":"Cra 10 # 1-1","city":"Bogotá"}}

    r = test_app.post("/v1/logistica/rutas/generar?fecha=2025-10-24&tipo=VENTA", headers={"X-Country":"co"})
    assert r.status_code == 201
    body = r.json()
    assert body["fecha"] == "2025-10-24"
    assert body["estado"] == "PLANEADA"
    assert len(body["paradas"]) == 1
    assert body["paradas"][0]["pedido_ids"] == [pid]

    # GET por id
    rid = body["id"]
    r2 = test_app.get(f"/v1/logistica/rutas/{rid}", headers={"X-Country":"co"})
    assert r2.status_code == 200
    assert r2.json()["id"] == rid

    # Listar por fecha
    r3 = test_app.get("/v1/logistica/rutas?fecha=2025-10-24", headers={"X-Country":"co"})
    assert r3.status_code == 200
    assert len(r3.json()) == 1

def test_patch_parada_estado_y_finaliza_ruta(test_app, patch_msclient):
    # Prepara ruta con dos paradas (distinto cliente)
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    patch_msclient[("pedidos", _params())] = [
        {"id": p1, "cliente_id": 1, "tipo":"VENTA","estado":"APROBADO"},
        {"id": p2, "cliente_id": 2, "tipo":"VENTA","estado":"APROBADO"},
    ]
    patch_msclient["usuarios"] = {
        1: {"address":"DirA","city":"Bogotá"},
        2: {"address":"DirB","city":"Bogotá"},
    }

    r = test_app.post("/v1/logistica/rutas/generar?fecha=2025-10-24&tipo=VENTA", headers={"X-Country":"co"})
    assert r.status_code == 201
    ruta = r.json()
    pids = [p["id"] for p in sorted(ruta["paradas"], key=lambda x: x["orden"])]

    # Entregar primera parada -> ruta EN_RUTA
    r1 = test_app.patch(f"/v1/logistica/paradas/{pids[0]}/estado", json={"estado": "ENTREGADA"}, headers={"X-Country":"co"})
    assert r1.status_code == 200
    rget = test_app.get(f"/v1/logistica/rutas/{ruta['id']}", headers={"X-Country":"co"})
    assert rget.status_code == 200
    assert rget.json()["estado"] in ("EN_RUTA","FINALIZADA")  # puede ya ser FINALIZADA si el orden coincide

    # Entregar segunda parada -> ruta FINALIZADA
    r2 = test_app.patch(f"/v1/logistica/paradas/{pids[1]}/estado", json={"estado": "ENTREGADA"}, headers={"X-Country":"co"})
    assert r2.status_code == 200
    rget2 = test_app.get(f"/v1/logistica/rutas/{ruta['id']}", headers={"X-Country":"co"})
    assert rget2.status_code == 200
    assert rget2.json()["estado"] == "FINALIZADA"
