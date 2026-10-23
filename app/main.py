from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, profiles, marketplace, confessions, launchpad, notifications, chat
from app.core.config import settings
from app.db.session import engine
from app.db.models import Base

Base.metadata.create_all(bind=engine)

import asyncio
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from app.core.redis import redis_service
from app.db.session import SessionLocal
from app.db.models import Confession, MarketplaceItem, ConfessionLike, MarketplaceInterest
from app.core.azure_storage import delete_marketplace_blob

async def purge_expired_confessions_loop():
    while True:
        try:
            with SessionLocal() as db:
                cutoff = datetime.utcnow() - timedelta(hours=48)
                expired_confessions = db.query(Confession.id).filter(Confession.created_at < cutoff).all()
                expired_confession_ids = [c[0] for c in expired_confessions]
                
                if expired_confession_ids:
                    db.query(ConfessionLike).filter(ConfessionLike.confession_id.in_(expired_confession_ids)).delete(synchronize_session=False)
                    db.query(Confession).filter(Confession.id.in_(expired_confession_ids)).delete(synchronize_session=False)
                
                bazaar_cutoff = datetime.utcnow() - timedelta(days=14)
                expired_items = db.query(MarketplaceItem).filter(MarketplaceItem.created_at < bazaar_cutoff).all()
                if expired_items:
                    expired_item_ids = [i.id for i in expired_items]
                    # Clean up orphaned images from Azure Blob Storage
                    for item in expired_items:
                        if item.image_url:
                            delete_marketplace_blob(item.image_url, owner_user_id=item.user_id)
                    
                    db.query(MarketplaceInterest).filter(MarketplaceInterest.item_id.in_(expired_item_ids)).delete(synchronize_session=False)
                    db.query(MarketplaceItem).filter(MarketplaceItem.id.in_(expired_item_ids)).delete(synchronize_session=False)
                
                db.commit()
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

is_prod = (settings.ENV or "").lower() == "production"

app = FastAPI(
    title="College Connect API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if is_prod else "/docs",
    redoc_url=None if is_prod else "/redoc",
    openapi_url=None if is_prod else "/openapi.json"
)

if not is_prod:
    try:
        from prometheus_fastapi_instrumentator import Instrumentator
        Instrumentator().instrument(app).expose(app)
    except Exception:
        pass

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
