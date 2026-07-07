import os
from sqlalchemy import create_engine, text
from app.core.config import Settings
s=Settings()
e=create_engine(s.DATABASE_URL)
with e.connect() as conn:
    rows=conn.execute(text('SELECT id, image_url FROM student_profiles')).fetchall()
    print(rows)
