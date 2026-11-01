import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock
import asyncio
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.models import Base, User
from app.schemas.intercollege import CampusEventCreate, EventRsvpRequest
from app.core.dependencies import AuthenticatedUser
from app.api.events import create_event, toggle_event_rsvp


class TestCampusEvents(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'events.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.TestingSession = sessionmaker(bind=self.engine)
        self.session = self.TestingSession()
        self.db_patch = patch("app.core.database.SessionLocal", self.TestingSession)
        self.cache_patch = patch("app.api.events._clear_events_cache", new_callable=AsyncMock)
        self.db_patch.start()
        self.cache_patch.start()

        user1 = User(id=1, email="student1@iit.ac.in", college_domain="iit.ac.in", password_hash="hash", is_verified=True)
        user2 = User(id=2, email="student2@iit.ac.in", college_domain="iit.ac.in", password_hash="hash", is_verified=True)
        self.session.add_all([user1, user2])
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.db_patch.stop()
        self.cache_patch.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def test_create_and_rsvp_event(self):
        async def run():
            user1 = AuthenticatedUser(id=1, email="student1@iit.ac.in", college_domain="iit.ac.in", is_verified=True, is_admin=False)
            user2 = AuthenticatedUser(id=2, email="student2@iit.ac.in", college_domain="iit.ac.in", is_verified=True, is_admin=False)

            event_in = CampusEventCreate(
                title="Hackathon 2026",
                description="Build awesome campus projects",
                event_date=datetime.utcnow() + timedelta(days=2),
                venue="LH-101",
                category="Hackathon",
                scope="college"
            )

            created = await create_event(event_in, user1)
            self.assertIsNotNone(created.id)
            self.assertEqual(created.title, "Hackathon 2026")
            self.assertEqual(created.rsvp_count, 0)

            # User 2 RSVPs
            rsvp_res = await toggle_event_rsvp(created.id, user2)
            self.assertTrue(rsvp_res["rsvped"])
            self.assertEqual(rsvp_res["rsvp_count"], 1)
            self.assertEqual(rsvp_res["going_count"], 1)
            self.assertEqual(rsvp_res["interested_count"], 0)

            # Changing from Going to Interested updates the one RSVP.
            rsvp_res2 = await toggle_event_rsvp(
                created.id,
                user2,
                EventRsvpRequest(status="interested"),
            )
            self.assertTrue(rsvp_res2["rsvped"])
            self.assertEqual(rsvp_res2["status"], "interested")
            self.assertEqual(rsvp_res2["rsvp_count"], 1)
            self.assertEqual(rsvp_res2["going_count"], 0)
            self.assertEqual(rsvp_res2["interested_count"], 1)

            # Selecting Interested again toggles the RSVP off.
            rsvp_res3 = await toggle_event_rsvp(
                created.id,
                user2,
                EventRsvpRequest(status="interested"),
            )
            self.assertFalse(rsvp_res3["rsvped"])
            self.assertEqual(rsvp_res3["rsvp_count"], 0)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
