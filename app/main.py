from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, profiles, marketplace, confessions, launchpad, notifications, chat
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
    pass

try:
    with engine.begin() as conn:
        conn.execute("ALTER TABLE marketplace_items ADD COLUMN image_url VARCHAR(255) NULL;")
except Exception:
    pass
sync_auth_schema(engine)

import asyncio
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from app.core.redis import redis_service
from app.db.session import SessionLocal
from app.db.models import Confession, MarketplaceItem, ConfessionLike, MarketplaceInterest

async def purge_expired_confessions_loop():
    while True:
        try:
            db = SessionLocal()
            cutoff = datetime.utcnow() - timedelta(hours=48)
            expired_confessions = db.query(Confession.id).filter(Confession.created_at < cutoff).all()
            expired_confession_ids = [c[0] for c in expired_confessions]
            
            deleted_count = 0
            if expired_confession_ids:
                db.query(ConfessionLike).filter(ConfessionLike.confession_id.in_(expired_confession_ids)).delete(synchronize_session=False)
                deleted_count = db.query(Confession).filter(Confession.id.in_(expired_confession_ids)).delete(synchronize_session=False)
            
            bazaar_cutoff = datetime.utcnow() - timedelta(days=14)
            expired_items = db.query(MarketplaceItem.id).filter(MarketplaceItem.created_at < bazaar_cutoff).all()
            expired_item_ids = [i[0] for i in expired_items]
            
            bazaar_deleted_count = 0
            if expired_item_ids:
                db.query(MarketplaceInterest).filter(MarketplaceInterest.item_id.in_(expired_item_ids)).delete(synchronize_session=False)
                bazaar_deleted_count = db.query(MarketplaceItem).filter(MarketplaceItem.id.in_(expired_item_ids)).delete(synchronize_session=False)
            
            db.commit()
            db.close()
        except Exception as e:
            print(f"[Purge Task] Error: {e}")
        await asyncio.sleep(12 * 3600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_service.get_client()
    purge_task = asyncio.create_task(purge_expired_confessions_loop())
    yield
    purge_task.cancel()
    await redis_service.close()

app = FastAPI(
    title="College Connect API",
    version="0.1.0",
    lifespan=lifespan,
    max_content_length=10 * 1024 * 1024
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(profiles.router, prefix="/api")
app.include_router(marketplace.router, prefix="/api")
app.include_router(confessions.router, prefix="/api")
app.include_router(launchpad.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(chat.router, prefix="/api")

@app.get("/")
def root():
    return {"message": "College Connect backend is running"}

# ✅ Add health endpoint for Azure Container Apps probes
@app.get("/healthz")
def healthz():
    return {"status": "ok", "env": settings.ENV}
