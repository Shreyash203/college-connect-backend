import os
import sqlite3
import tempfile
import unittest

from sqlalchemy import create_engine, text

from app.db.models import Base
from app.db.schema_sync import sync_auth_schema


class SchemaSyncTests(unittest.TestCase):
    def test_sync_auth_schema_adds_missing_reset_password_columns(self):
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)

        try:
            connection = sqlite3.connect(db_path)
            connection.execute(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    email VARCHAR NOT NULL,
                    password_hash VARCHAR NOT NULL,
                    is_verified BOOLEAN,
                    verification_otp VARCHAR,
                    verification_otp_expires_at DATETIME,
                    created_at DATETIME
                )
                """
            )
            connection.commit()
            connection.close()

            engine = create_engine(f"sqlite:///{db_path}")
            Base.metadata.create_all(bind=engine)
            sync_auth_schema(engine)

            with engine.begin() as db_connection:
                columns = {
                    row[1]
                    for row in db_connection.execute(text("PRAGMA table_info('users')")).fetchall()
                }

            self.assertIn("reset_password_otp", columns)
            self.assertIn("reset_password_otp_expires_at", columns)
        finally:
            try:
                engine.dispose()
            except UnboundLocalError:
                pass
            os.remove(db_path)


if __name__ == "__main__":
    unittest.main()
