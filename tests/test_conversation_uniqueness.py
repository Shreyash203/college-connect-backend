import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from app.db.models import Base, User, StudentProfile, Conversation
from app.api.chat import start_conversation
from app.core.dependencies import AuthenticatedUser


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()

    # Seed users
    u1 = User(id=5, email="student5@college.edu", password_hash="hash", is_verified=True)
    u2 = User(id=8, email="student8@college.edu", password_hash="hash", is_verified=True)
    session.add_all([u1, u2])
    session.commit()

    yield session

    session.close()


def test_canonical_conversation_ordering(test_db):
    user5 = AuthenticatedUser(id=5, email="student5@college.edu", college_domain="college.edu", is_verified=True, is_admin=False)
    user8 = AuthenticatedUser(id=8, email="student8@college.edu", college_domain="college.edu", is_verified=True, is_admin=False)

    # User 8 initiates conversation with User 5 (target=5, current=8)
    conv1 = start_conversation(target_user_id=5, current_user=user8, db=test_db)
    # Canonical ordering: user1_id must be min(5, 8) = 5, user2_id must be max(5, 8) = 8
    assert conv1.user1_id == 5
    assert conv1.user2_id == 8

    # User 5 initiates conversation with User 8 (target=8, current=5)
    conv2 = start_conversation(target_user_id=8, current_user=user5, db=test_db)
    # Must return the exact same conversation ID
    assert conv2.id == conv1.id
    assert conv2.user1_id == 5
    assert conv2.user2_id == 8

    # Assert only 1 conversation row exists in DB
    total = test_db.query(Conversation).count()
    assert total == 1


def test_unique_constraint_blocks_duplicate_insert(test_db):
    # Direct database insertion test
    c1 = Conversation(user1_id=5, user2_id=8)
    test_db.add(c1)
    test_db.commit()

    # Attempting to insert duplicate pair must raise IntegrityError
    c2 = Conversation(user1_id=5, user2_id=8)
    test_db.add(c2)
    with pytest.raises(IntegrityError):
        test_db.commit()
