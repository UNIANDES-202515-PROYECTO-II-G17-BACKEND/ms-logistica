# src/domain/models.py
from __future__ import annotations
import enum, uuid
from datetime import datetime, date
from typing import List, Optional
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

class Base(DeclarativeBase):
    pass

class RutaEstado(str, enum.Enum):
    PLANEADA = "PLANEADA"
    EN_RUTA = "EN_RUTA"
    FINALIZADA = "FINALIZADA"
    CANCELADA = "CANCELADA"

class ParadaEstado(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    ENTREGADA = "ENTREGADA"
    FALLIDA = "FALLIDA"

class RutaEntrega(Base):
    __tablename__ = "ruta_entrega"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    estado: Mapped[RutaEstado] = mapped_column(Enum(RutaEstado), nullable=False, default=RutaEstado.PLANEADA)
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    paradas: Mapped[List["Parada"]] = relationship("Parada", back_populates="ruta", cascade="all, delete-orphan", lazy="selectin")

class Parada(Base):
    __tablename__ = "parada"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ruta_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ruta_entrega.id"), nullable=False)
    cliente_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    direccion: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ciudad: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    estado: Mapped[ParadaEstado] = mapped_column(Enum(ParadaEstado), nullable=False, default=ParadaEstado.PENDIENTE)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    ruta: Mapped["RutaEntrega"] = relationship("RutaEntrega", back_populates="paradas")
    # Relación con la tabla puente (cada fila trae un pedido_id remoto)
    pedidos: Mapped[List["ParadaPedido"]] = relationship(
        "ParadaPedido", back_populates="parada", cascade="all, delete-orphan", lazy="selectin"
    )

class ParadaPedido(Base):
    __tablename__ = "parada_pedido"
    # FK SOLO a parada; pedido_id es UUID sin FK (vive en otro microservicio)
    parada_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parada.id"), primary_key=True)
    pedido_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    parada: Mapped["Parada"] = relationship("Parada", back_populates="pedidos", lazy="selectin")

    __table_args__ = (UniqueConstraint("parada_id", "pedido_id", name="uq_parada_pedido"),)
