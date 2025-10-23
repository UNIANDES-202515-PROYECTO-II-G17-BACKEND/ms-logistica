import os
from datetime import timedelta


class Settings:

    SERVICE_NAME = os.getenv("SERVICE_NAME", "ms-logistica")
    VERSION = os.getenv("VERSION", "0.1.0")
    REGION = os.getenv("REGION", "us-central1")

    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASS", "postgres")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "5432"))
    DB_NAME = os.getenv("DB_NAME", "db_ms_logistica")

    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = os.getenv("REDIS_PORT", "6379")

    SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )

    DEFAULT_SCHEMA = os.getenv("DEFAULT_SCHEMA", "co")
    COUNTRY_HEADER = os.getenv("COUNTRY_HEADER", "X-Country")
    GATEWAY_BASE_URL = os.getenv("GATEWAY_BASE_URL", "https://medisupply-gw-5k2l9pfv.uc.gateway.dev")
    USERS_CLIENTE_DETALLE_PATH = "/v1/usuarios/usuario/{cliente_id}"
    PEDIDOS_LISTAR_PATH = "/v1/pedidos"
    PEDIDO_MARCAR_DESPACHADO_PATH = "/v1/pedidos/{pedido_id}/marcar-despachado"
    PEDIDOS_LISTAR_DEFAULTS = {
        "limit": 200,
        "offset": 0,
        "tipo": "VENTA",
        "estado": "APROBADO"
    }

settings = Settings()
