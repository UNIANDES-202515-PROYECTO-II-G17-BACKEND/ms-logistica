import uuid

from fastapi import Header, Request
from dataclasses import dataclass
from src.config import settings
from src.infrastructure.infrastructure import session_for_schema

@dataclass
class AuditContext:
    request_id: str
    country: str | None
    user_id: int | None
    ip: str | None


def get_session(X_Country: str | None = Header(default=None, alias=settings.COUNTRY_HEADER)):
    schema = (X_Country or settings.DEFAULT_SCHEMA).strip().lower()
    with session_for_schema(schema) as session:
        yield session

def audit_context(request: Request) -> AuditContext:
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    uid = None
    country = request.headers.get("X-Country")
    ip = request.headers.get("X-Forwarded-For") or request.client.host if request.client else None
    return AuditContext(request_id=rid, country=country, user_id=uid, ip=ip)