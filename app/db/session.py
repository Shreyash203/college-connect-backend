from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

connect_args = {}
database_url = settings.DATABASE_URL
if database_url is None:
    raise RuntimeError("DATABASE_URL is required. Set DATABASE_URL in environment variables or Azure Key Vault.")

if database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine_kwargs = {"connect_args": connect_args}
if not database_url.startswith("sqlite"):
    engine_kwargs.update({"pool_pre_ping": True, "pool_recycle": 300})

engine = create_engine(database_url, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
