from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, profiles, marketplace
from app.core.config import settings
from app.db.session import engine
from app.db.models import Base
from app.db.schema_sync import sync_auth_schema

Base.metadata.create_all(bind=engine)

# Ensure image_url column exists for existing tables
try:
    with engine.begin() as conn:
        conn.execute("ALTER TABLE student_profiles ADD COLUMN image_url VARCHAR(255) NULL;")
except Exception:
    # Column may already exist; ignore any errors
    pass

try:
    with engine.begin() as conn:
        conn.execute("ALTER TABLE marketplace_items ADD COLUMN image_url VARCHAR(255) NULL;")
except Exception:
    pass
sync_auth_schema(engine)

from contextlib import asynccontextmanager
from app.core.redis import redis_service

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize connection client
    redis_service.get_client()
    yield
    # Close connection client pool
    await redis_service.close()

app = FastAPI(
    title="College Connect API",
    version="0.1.0",
    lifespan=lifespan,
    max_content_length=10 * 1024 * 1024  # Enforce 10 MB file size limit
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
app.include_router(marketplace.router, prefix="/api")

@app.get("/")
def root():
    return {"message": "College Connect backend is running"}

# ✅ Add health endpoint for Azure Container Apps probes
@app.get("/healthz")
def healthz():
    return {"status": "ok", "env": settings.ENV}

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
app.include_router(marketplace.router, prefix="/api")

@app.get("/")
def root():
    return {"message": "College Connect backend is running"}

# ✅ Add health endpoint for Azure Container Apps probes
@app.get("/healthz")
def healthz():
    return {"status": "ok", "env": settings.ENV}