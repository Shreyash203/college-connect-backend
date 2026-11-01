import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.api import chat, confessions, events, launchpad, marketplace
from app.core import database
from app.core.dependencies import AuthenticatedUser
from app.core.verified_dependencies import get_current_verified_user
from app.db.models import Base, Conversation, Message, Notification, User, StudentApp
from app.schemas.intercollege import ConfessionCreate
from app.schemas.marketplace import MarketplaceItemCreate


@pytest.fixture
def storage(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrency.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database, 'SessionLocal', factory)
    monkeypatch.setattr(chat, 'SessionLocal', factory)
    with factory() as db:
        db.add_all([
            User(id=1, email='one@alpha.ac.in', college_domain='alpha.ac.in', password_hash='hash', is_verified=True),
            User(id=2, email='two@alpha.ac.in', college_domain='alpha.ac.in', password_hash='hash', is_verified=True),
            User(id=3, email='three@other.ac.in', college_domain='other.ac.in', password_hash='hash', is_verified=True),
        ])
        db.commit()
    yield engine, factory
    engine.dispose()


@pytest.fixture
def user():
    return AuthenticatedUser(1, 'one@alpha.ac.in', 'alpha.ac.in', True, False)


@pytest.fixture
def redis(monkeypatch):
    async def scan_iter(**kwargs):
        for key in []:
            yield key

    client = SimpleNamespace(get=AsyncMock(return_value=None), setex=AsyncMock(),
                             keys=AsyncMock(return_value=[]), delete=AsyncMock(), scan_iter=scan_iter)
    monkeypatch.setattr(confessions.redis_service, 'get_client', lambda: client)
    return client


def test_slow_database_request_does_not_block_other_http_requests(storage, user):
    engine, _ = storage
    entered, release = threading.Event(), threading.Event()

    def slow_query(conn, cursor, statement, parameters, context, executemany):
        if 'marketplace_items' in statement.lower() and statement.lstrip().upper().startswith('SELECT'):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('Other request could not run while the query was waiting')

    event.listen(engine, 'before_cursor_execute', slow_query)
    app = FastAPI()
    app.include_router(marketplace.router)
    app.include_router(events.router)
    app.dependency_overrides[get_current_verified_user] = lambda: user

    @app.get('/ping')
    async def ping():
        return {'ok': True}

    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            pending = asyncio.create_task(client.get('/marketplace/items'))
            try:
                async def wait_for_query():
                    while not entered.is_set():
                        await asyncio.sleep(.005)
                await asyncio.wait_for(wait_for_query(), 2)
                response = await asyncio.wait_for(client.get('/ping'), 1)
                assert response.json() == {'ok': True}
                other_db_response = await asyncio.wait_for(client.get('/events/'), 1)
                assert other_db_response.status_code == 200
                assert not pending.done()
            finally:
                release.set()
                result = await pending
            assert result.status_code == 200

    try:
        asyncio.run(check())
    finally:
        event.remove(engine, 'before_cursor_execute', slow_query)


def test_session_lifetime_and_rollback_stay_in_worker(storage, monkeypatch):
    _, factory = storage
    loop_thread = threading.get_ident()
    seen = []

    class TrackedSession(Session):
        def __init__(self, *args, **kwargs):
            seen.append(('open', threading.get_ident()))
            super().__init__(*args, **kwargs)

        def close(self):
            seen.append(('close', threading.get_ident()))
            super().close()

    monkeypatch.setattr(database, 'SessionLocal', sessionmaker(bind=storage[0], class_=TrackedSession))

    def failing(db):
        seen.append(('query', threading.get_ident()))
        db.add(User(id=99, email='rollback@alpha.ac.in', password_hash='hash'))
        db.flush()
        raise HTTPException(403, 'denied')

    with pytest.raises(HTTPException, match='denied'):
        asyncio.run(database.run_db(failing))
    assert [kind for kind, _ in seen] == ['open', 'query', 'close']
    assert len({tid for _, tid in seen}) == 1
    assert seen[0][1] != loop_thread
    with factory() as db:
        assert db.get(User, 99) is None


def test_feed_operations_serialize_lazy_relationships_in_worker(storage, user, redis):
    engine, factory = storage
    loop_thread = threading.get_ident()
    query_threads = []

    def record(*args):
        query_threads.append(threading.get_ident())

    with factory() as db:
        db.add(StudentApp(user_id=1, college_domain='alpha.ac.in', app_name='Example', description='A project', app_url='https://example.com'))
        db.commit()
    event.listen(engine, 'before_cursor_execute', record)

    async def check():
        confession = await confessions.create_confession(ConfessionCreate(content='Hello campus', scope='global'), user)
        listing = await marketplace.create_marketplace_item(MarketplaceItemCreate(title='Book', description='A textbook', image_url=''), user)
        feed = await confessions.get_all_confessions(0, 20, 'global', user)
        items = await marketplace.list_marketplace_items(None, 0, 20, user)
        apps = await launchpad.get_all_apps(0, 20, user)
        assert feed[0].id == confession.id
        assert items[0]['id'] == listing['id']
        assert items[0]['email'] == user.email
        assert apps[0].email == user.email
        await confessions.delete_confession(confession.id, user)
        await marketplace.delete_marketplace_item(listing['id'], user)
        assert await confessions.get_all_confessions(0, 20, 'global', user) == []

    try:
        asyncio.run(check())
        assert query_threads
        assert loop_thread not in query_threads
    finally:
        event.remove(engine, 'before_cursor_execute', record)


def test_chat_persistence_preserves_authorization_and_notifications(storage):
    _, factory = storage
    with factory() as db:
        conv = Conversation(user1_id=1, user2_id=2)
        db.add(conv)
        db.commit()
        cid = conv.id
    assert chat.persist_chat_message(3, cid, 'unauthorized') is None
    target, message = chat.persist_chat_message(1, cid, 'hello')
    assert target == 2
    assert message['content'] == 'hello'
    with factory() as db:
        assert db.query(Message).count() == 1
        assert db.query(Notification).filter_by(user_id=2).count() == 1
        assert db.get(Conversation, cid).updated_at is not None
