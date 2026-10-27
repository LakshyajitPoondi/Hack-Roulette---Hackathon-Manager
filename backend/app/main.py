from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from urllib.parse import urlsplit

from app.api import admin, auth, certificates, datasets, emails, participants
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(title="Tech Roulette API", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type"])


@app.middleware("http")
async def check_origin(request: Request, call_next):
    if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
        origin = request.headers.get("origin")
        origin_host = urlsplit(origin).netloc if origin else ""
        request_host = request.headers.get("host", "")
        if origin and origin != settings.frontend_origin and origin_host != request_host:
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
    return await call_next(request)


app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(participants.router)
app.include_router(datasets.router)
app.include_router(certificates.router)
app.include_router(emails.router)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse({"detail": jsonable_encoder(exc.errors())}, status_code=422)


@app.get("/api/health")
def health():
    return {"status": "ok"}
