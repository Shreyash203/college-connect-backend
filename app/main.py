from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, profiles
from app.core.config import settings
from app.db.session import engine
from app.db.models import Base
from app.db.schema_sync import sync_auth_schema

Base.metadata.create_all(bind=engine)
sync_auth_schema(engine)

app = FastAPI(
    title="College Connect API",
    version="0.1.0"
)

# ✅ Use env-based CORS (NOT "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,   # e.g. ["https://your-frontend.azurestaticapps.net"]
    allow_credentials=True,                     # usually needed for auth flows
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(profiles.router, prefix="/api")

@app.get("/")
def root():
    return {"message": "College Connect backend is running"}

# ✅ Add health endpoint for Azure Container Apps probes
@app.get("/healthz")
def healthz():
    return {"status": "ok", "env": settings.ENV}