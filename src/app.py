import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import logging, sys

from .domain import models
from sqlalchemy import inspect
from src.infrastructure.infrastructure import engine
from .config import settings
from .routes.health import router as health_router
from .routes.logistica import router as logistica_router
from src.errors import NotFoundError, ConflictError



log = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

KNOWN_SCHEMAS = ["co","ec","mx","pe"]  # o desde ENV

@asynccontextmanager
async def lifespan(app):
    for schema in KNOWN_SCHEMAS:
        try:
            eng = engine.execution_options(schema_translate_map={None: schema})
            models.Base.metadata.create_all(bind=eng)
            inspector = inspect(eng)
            tables = inspector.get_table_names(schema=schema)
            log.info(f"✅ {len(tables)} tablas creadas/verificadas en schema '{schema}': {tables}")
        except Exception as e:
            log.error(f"❌ Error creando tablas en schema {schema}: {e}")
    yield
    log.info("🛑 Finalizando aplicación ms-logistica")

app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.VERSION,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})

@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})

app.include_router(health_router)
app.include_router(logistica_router)