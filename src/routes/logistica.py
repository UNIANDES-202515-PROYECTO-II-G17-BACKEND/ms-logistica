from fastapi import APIRouter, Depends, Query, Body
from datetime import date
from uuid import UUID
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional  # <-- si lo requieres

from src.dependencies import get_session, audit_context, AuditContext
from src.services import logistica_service   # <-- nombre correcto
from src.domain.schemas import RutaEntregaOut, ParadaOut
from src.domain.models import ParadaEstado

router = APIRouter(prefix="/v1/logistica", tags=["logistica"])

def _serialize_ruta(ruta) -> RutaEntregaOut:
    return RutaEntregaOut(
        id=ruta.id,
        fecha=ruta.fecha,
        estado=ruta.estado,
        creado_en=ruta.creado_en,
        paradas=[
            ParadaOut(
                id=pa.id,
                cliente_id=pa.cliente_id,
                direccion=pa.direccion,
                ciudad=pa.ciudad,
                estado=pa.estado,
                orden=pa.orden,
                # OJO: ahora 'pa.pedidos' son vínculos (ParadaPedido)
                pedido_ids=[v.pedido_id for v in getattr(pa, "pedidos", [])],
            )
            for pa in ruta.paradas
        ],
    )

@router.post("/rutas/generar", response_model=RutaEntregaOut, status_code=201)
def generar_ruta(
    fecha: date = Query(..., description="Fecha de compromiso (YYYY-MM-DD)"),
    tipo: str = Query("VENTA", description="Tipo de pedido a considerar (VENTA/COMPRA)"),
    fc_desde: Optional[date] = Query(None, description="Fecha compromiso desde"),
    fc_hasta: Optional[date] = Query(None, description="Fecha compromiso hasta"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    audit: AuditContext = Depends(audit_context),
):
    ruta = logistica_service.generar_ruta(
        session, fecha, audit,
        tipo=tipo,
        fc_desde=fc_desde, fc_hasta=fc_hasta,
        limit=limit, offset=offset
    )
    return _serialize_ruta(ruta)

@router.get("/rutas/{ruta_id}", response_model=RutaEntregaOut)
def obtener_ruta(
    ruta_id: UUID,
    session: Session = Depends(get_session),
):
    ruta = logistica_service.obtener_ruta(session, ruta_id)
    return _serialize_ruta(ruta)

@router.get("/rutas", response_model=list[RutaEntregaOut])
def listar_rutas(
    fecha: date = Query(..., description="Fecha de compromiso"),
    session: Session = Depends(get_session),
):
    rutas = logistica_service.listar_rutas_por_fecha(session, fecha)
    return [_serialize_ruta(r) for r in rutas]

class ParadaEstadoIn(BaseModel):
    estado: ParadaEstado

@router.patch("/paradas/{parada_id}/estado", response_model=ParadaOut)
def actualizar_estado_parada(
    parada_id: UUID,
    payload: ParadaEstadoIn = Body(...),
    session: Session = Depends(get_session),
):
    pa = logistica_service.actualizar_estado_parada(session, parada_id, payload.estado)
    return ParadaOut(
        id=pa.id,
        cliente_id=pa.cliente_id,
        direccion=pa.direccion,
        ciudad=pa.ciudad,
        estado=pa.estado,
        orden=pa.orden,
        pedido_ids=[v.pedido_id for v in getattr(pa, "pedidos", [])],
    )
