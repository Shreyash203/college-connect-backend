from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

connect_args = {}
database_url = settings.DATABASE_URL
if database_url is None:
    raise RuntimeError("DATABASE_URL is required. Set DATABASE_URL in environment variables or Azure Key Vault.")

if database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(database_url, connect_args=connect_args)

# Add new column for profile image if it doesn't exist (ignore errors if already present)
try:
    with engine.begin() as conn:
        conn.execute("ALTER TABLE student_profiles ADD COLUMN image_url VARCHAR(255) NULL;")
except Exception:
    # Column likely already exists or DB engine doesn't support the operation; safe to ignore
    pass
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
