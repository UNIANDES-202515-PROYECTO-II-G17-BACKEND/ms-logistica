from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

class DomainError(Exception): ...
class NotFoundError(DomainError): ...
class ConflictError(DomainError): ...
class ValidationError(DomainError): ...

def register_error_handlers(app: FastAPI):
    @app.exception_handler(NotFoundError)
    async def nf_handler(request: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def cf_handler(request: Request, exc: ConflictError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValidationError)
    async def val_handler(request: Request, exc: ValidationError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})