# src/services/logistica_service.py
from datetime import date
from collections import defaultdict
from typing import Optional, Dict, Tuple, List
import time
import logging
from uuid import UUID
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import select

from src.errors import NotFoundError, ConflictError
from src.domain.models import RutaEntrega, Parada, ParadaPedido, RutaEstado, ParadaEstado
from src.dependencies import AuditContext
from src.config import Settings
from src.infrastructure.http import MsClient

logger = logging.getLogger(__name__)

TIPO_VENTA = "VENTA"
EST_APROBADO = "APROBADO"

MAX_RETRIES = 3
RETRY_SLEEP_SEC = 0.6


# ---------- Helpers MS externos ----------

def _normalize(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = s.strip()
    return s.casefold() if s else None


def _ms_usuarios_detalle(
    ms: MsClient,
    cliente_id: Optional[int],
    cache: Dict[int, Dict[str, Optional[str]]],
) -> Dict[str, Optional[str]]:
    """
    Devuelve {"direccion": str|None, "ciudad": str|None} consultando ms-usuarios.
    Usa caché por cliente. Tolera errores devolviendo None/None.
    """
    if not cliente_id:
        return {"direccion": None, "ciudad": None}
    if cliente_id in cache:
        return cache[cliente_id]
    try:
        path = Settings.USERS_CLIENTE_DETALLE_PATH.format(cliente_id=cliente_id)
        logger.debug("Consultando ms-usuarios: path=%s cliente_id=%s", path, cliente_id)
        data = ms.get(path)
        out = {
            # mapeamos a claves internas en español, pero aceptamos inglés al leer
            "direccion": data.get("direccion") or data.get("address"),
            "ciudad": data.get("ciudad") or data.get("city"),
        }
        logger.debug("Respuesta ms-usuarios cliente_id=%s -> %s", cliente_id, out)
        cache[cliente_id] = out
        return out
    except Exception as e:
        logger.warning("Fallo ms-usuarios cliente_id=%s: %s", cliente_id, e)
        out = {"direccion": None, "ciudad": None}
        cache[cliente_id] = out
        return out


def _ms_pedidos_listar_aprobados(
    ms: MsClient, *, fecha: date, tipo: str,
    fc_desde: Optional[date], fc_hasta: Optional[date],
    limit: int, offset: int
) -> List[dict]:
    params = {
        "tipo": tipo,
        "estado": EST_APROBADO,
        "fecha_compromiso": fecha.isoformat(),
        "limit": str(limit),
        "offset": str(offset),
    }
    if fc_desde:
        params["fc_desde"] = fc_desde.isoformat()
    if fc_hasta:
        params["fc_hasta"] = fc_hasta.isoformat()

    logger.info("Listando pedidos aprobados en ms-pedidos: params=%s", params)
    try:
        resp = ms.get(Settings.PEDIDOS_LISTAR_PATH, params=params)
        if isinstance(resp, list):
            logger.debug("ms-pedidos devolvió lista con %d elementos", len(resp))
            return resp
        if isinstance(resp, dict):
            items = resp.get("items", [])
            logger.debug("ms-pedidos devolvió dict con %d items", len(items))
            return items
        logger.debug("ms-pedidos devolvió tipo no esperado (%s). Se asume lista vacía.", type(resp))
        return []
    except Exception as e:
        logger.error("Error consultando ms-pedidos: %s", e)
        raise NotFoundError(f"No fue posible consultar pedidos aprobados: {e}")


def _ms_pedido_marcar_despachado(ms: MsClient, pedido_id: str) -> bool:
    path = Settings.PEDIDO_MARCAR_DESPACHADO_PATH.format(pedido_id=pedido_id)
    last_exc = None
    for intento in range(1, MAX_RETRIES + 1):
        try:
            logger.debug(
                "Marcando pedido como DESPACHADO en ms-pedidos (intento %d/%d): pedido_id=%s",
                intento, MAX_RETRIES, pedido_id
            )
            _ = ms.post(path, json={})
            logger.info("Pedido marcado como DESPACHADO: pedido_id=%s", pedido_id)
            return True
        except Exception as e:
            last_exc = e
            logger.warning(
                "Fallo marcar-despachado pedido_id=%s (intento %d/%d): %s",
                pedido_id, intento, MAX_RETRIES, e
            )
            time.sleep(RETRY_SLEEP_SEC)
    logger.error("No se pudo marcar DESPACHADO pedido_id=%s. Último error: %s", pedido_id, last_exc)
    return False


# ---------- Casos de uso ----------

def generar_ruta(
    session: Session, fecha: date, audit: AuditContext, *,
    tipo: str = TIPO_VENTA,
    fc_desde: Optional[date] = None, fc_hasta: Optional[date] = None,
    limit: int = 200, offset: int = 0
) -> RutaEntrega:
    """
    Crea una RutaEntrega para `fecha` agrupando Paradas por (cliente_id, direccion, ciudad).
    Luego ordena a ms-pedidos marcar cada pedido como DESPACHADO (uno a uno).
    """
    x_country = audit.country or "co"
    logger.info(
        "Generar ruta: fecha=%s tipo=%s fc_desde=%s fc_hasta=%s limit=%s offset=%s X-Country=%s",
        fecha, tipo, fc_desde, fc_hasta, limit, offset, x_country
    )
    ms = MsClient(x_country=x_country)

    # 1) Obtener pedidos aprobados desde ms-pedidos
    pedidos = _ms_pedidos_listar_aprobados(
        ms, fecha=fecha, tipo=tipo, fc_desde=fc_desde, fc_hasta=fc_hasta, limit=limit, offset=offset
    )
    if not pedidos:
        logger.info("Sin pedidos aprobados para fecha=%s tipo=%s -> 404 negocio", fecha, tipo)
        raise NotFoundError("No hay ventas para generar ruta de entrega en la fecha seleccionada.")

    logger.debug("Pedidos recibidos: %d", len(pedidos))

    # 2) Evitar duplicados por fecha
    ya = session.execute(
        select(RutaEntrega).where(RutaEntrega.fecha == fecha, RutaEstado.CANCELADA != RutaEntrega.estado)
    ).scalars().first()
    if ya:
        logger.info("Ruta ya existente para fecha=%s id=%s estado=%s -> 409", fecha, ya.id, ya.estado)
        raise ConflictError(f"Ya existe una ruta para {fecha} (id={ya.id})")

    # 3) Enriquecer y agrupar
    cache_clientes: Dict[int, Dict[str, Optional[str]]] = {}
    grupos: Dict[Tuple[Optional[int], Optional[str], Optional[str]], list] = defaultdict(list)

    for ped in pedidos:
        # Convertimos el id a UUID para almacenar correctamente
        pid_raw = ped.get("id")
        try:
            pid: UUID = pid_raw if isinstance(pid_raw, uuid.UUID) else uuid.UUID(str(pid_raw))
        except Exception as e:
            logger.warning("Pedido con id inválido (%r); se omite. Error: %s", pid_raw, e)
            continue

        cliente_id = ped.get("cliente_id")
        info = _ms_usuarios_detalle(ms, cliente_id, cache_clientes)
        # <- toma en inglés primero (y deja fallback a español del helper)
        direccion = info.get("direccion") or info.get("address")  # normalmente viene 'address'
        ciudad = info.get("ciudad") or info.get("city")           # normalmente viene 'city'

        key = (cliente_id, _normalize(direccion), _normalize(ciudad))
        grupos[key].append((pid, cliente_id, direccion, ciudad))

    logger.debug("Total grupos (paradas) a crear: %d", len(grupos))

    # 4) Crear ruta y paradas
    ruta = RutaEntrega(fecha=fecha, estado=RutaEstado.PLANEADA)
    session.add(ruta)
    session.flush()
    logger.info("Ruta creada: id=%s fecha=%s estado=%s", ruta.id, ruta.fecha, ruta.estado)

    for idx, (key, lista) in enumerate(
        sorted(grupos.items(), key=lambda it: (str(it[0][0]), it[0][2] or "", it[0][1] or ""))
    ):
        _, _, _ = key
        _, cliente_original, direccion_original, ciudad_original = lista[0]

        parada = Parada(
            ruta_id=ruta.id,
            cliente_id=cliente_original,
            direccion=direccion_original,
            ciudad=ciudad_original,
            orden=idx + 1,
            estado=ParadaEstado.PENDIENTE,
        )
        session.add(parada)
        session.flush()
        logger.debug(
            "Parada creada: id=%s orden=%d cliente_id=%s ciudad=%s dir=%s pedidos=%d",
            parada.id, parada.orden, parada.cliente_id, parada.ciudad, parada.direccion, len(lista)
        )

        for (pedido_id, _cli, _dir, _ciu) in lista:
            session.add(ParadaPedido(parada_id=parada.id, pedido_id=pedido_id))

    session.commit()
    session.refresh(ruta)
    logger.info("Ruta confirmada en DB: id=%s paradas=%d", ruta.id, len(ruta.paradas))

    # 5) Marcar cada pedido como DESPACHADO (uno a uno) — fuera de la transacción
    all_ok = True
    for ped in pedidos:
        pid_raw = ped.get("id")
        try:
            pid_uuid: UUID = pid_raw if isinstance(pid_raw, uuid.UUID) else uuid.UUID(str(pid_raw))
        except Exception as e:
            logger.warning("No se marca DESPACHADO (id inválido) %r: %s", pid_raw, e)
            continue
        ok = _ms_pedido_marcar_despachado(ms, str(pid_uuid))
        all_ok = all_ok and ok

    if not all_ok:
        logger.warning("Algunos pedidos no se marcaron DESPACHADO en ms-pedidos. ruta_id=%s", ruta.id)

    logger.info("Generar ruta finalizado: ruta_id=%s", ruta.id)
    return ruta


def obtener_ruta(session: Session, ruta_id: UUID) -> RutaEntrega:
    logger.debug("Obtener ruta: ruta_id=%s", ruta_id)
    ruta = session.get(RutaEntrega, ruta_id)
    if not ruta:
        logger.info("Ruta no encontrada: ruta_id=%s -> 404", ruta_id)
        raise NotFoundError("Ruta no encontrada")
    _ = [p.pedidos for p in ruta.paradas]
    return ruta


def listar_rutas_por_fecha(session: Session, fecha: date) -> List[RutaEntrega]:
    logger.debug("Listar rutas por fecha: fecha=%s", fecha)
    rutas = session.execute(
        select(RutaEntrega).where(RutaEntrega.fecha == fecha)
    ).scalars().all()
    for r in rutas:
        _ = [p.pedidos for p in r.paradas]
    logger.info("Listar rutas: fecha=%s -> %d rutas", fecha, len(rutas))
    return rutas


def actualizar_estado_parada(session: Session, parada_id: UUID, nuevo_estado: ParadaEstado) -> Parada:
    logger.info("Actualizar estado parada: parada_id=%s nuevo_estado=%s", parada_id, nuevo_estado)
    pa: Parada = session.get(Parada, parada_id)
    if not pa:
        logger.info("Parada no encontrada: parada_id=%s -> 404", parada_id)
        raise NotFoundError("Parada no encontrada")

    ruta = session.get(RutaEntrega, pa.ruta_id)
    if not ruta:
        logger.info(
            "Ruta no encontrada para parada: parada_id=%s ruta_id=%s -> 404",
            parada_id, getattr(pa, "ruta_id", None)
        )
        raise NotFoundError("Ruta no encontrada para la parada")

    estado_anterior = pa.estado
    pa.estado = nuevo_estado
    session.add(pa)
    logger.debug("Parada %s: estado %s -> %s", pa.id, estado_anterior, nuevo_estado)

    if ruta.estado == RutaEstado.PLANEADA and nuevo_estado in (ParadaEstado.ENTREGADA, ParadaEstado.FALLIDA):
        logger.debug("Ruta %s cambia a EN_RUTA (antes %s)", ruta.id, ruta.estado)
        ruta.estado = RutaEstado.EN_RUTA
        session.add(ruta)

    session.flush()

    estados = [p.estado for p in ruta.paradas]
    if estados and all(st == ParadaEstado.ENTREGADA for st in estados):
        logger.info("Todas las paradas ENTREGADAS -> Ruta %s FINALIZADA", ruta.id)
        ruta.estado = RutaEstado.FINALIZADA
        session.add(ruta)

    session.commit()
    session.refresh(pa)
    logger.info(
        "Actualizar estado parada OK: parada_id=%s estado=%s ruta_id=%s ruta_estado=%s",
        pa.id, pa.estado, ruta.id, ruta.estado
    )
    return pa
