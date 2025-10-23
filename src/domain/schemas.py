from pydantic import BaseModel, Field
from uuid import UUID
from datetime import date, datetime
from typing import List, Optional
from .models import RutaEstado, ParadaEstado

class ParadaOut(BaseModel):
    id: UUID
    cliente_id: Optional[int] = None
    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    estado: ParadaEstado
    orden: int
    pedido_ids: List[UUID] = Field(default_factory=list)

    class Config:
        from_attributes = True

class RutaEntregaOut(BaseModel):
    id: UUID
    fecha: date
    estado: RutaEstado
    creado_en: datetime
    paradas: List[ParadaOut] = Field(default_factory=list)

    class Config:
        from_attributes = True
