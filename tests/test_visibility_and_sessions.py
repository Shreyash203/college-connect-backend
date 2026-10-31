import json
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import auth, profiles, marketplace, confessions, chat
from app.core import security
from app.core.dependencies import AuthenticatedUser, authenticate_session
from app.core.sessions import issue_session
from app.core.config import settings
from app.db.models import Base, User, StudentProfile, MarketplaceItem, Confession, MarketplaceInterest, ConfessionLike, Notification, AuthSession
from app.schemas.auth import ResetPasswordRequest, GoogleLoginRequest, VerifyRegistrationRequest


def immediate(coro):
    """Drive mocked, non-suspending coroutines without Windows socket-pair setup."""
    try:
        coro.send(None)
    except StopIteration as result:
        return result.value
    finally:
        coro.close()
    raise AssertionError('Unexpected external I/O in isolated regression test')


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(id=1, email='one@alpha.ac.in', college_domain='alpha.ac.in', password_hash='hash', is_verified=True),
        User(id=2, email='two@beta.ac.in', college_domain='beta.ac.in', password_hash='hash', is_verified=True),
        User(id=3, email='three@alpha.ac.in', college_domain='alpha.ac.in', password_hash='hash', is_verified=True),
    ])
    session.commit()
    # Overlapping ID spaces: profile id 3 belongs to user 2, not user 3.
    session.add_all([
        StudentProfile(id=10, user_id=1, display_name='One', year='2025'),
        StudentProfile(id=3, user_id=2, display_name='Two', year='2025'),
        StudentProfile(id=20, user_id=3, display_name='Three', year='2025'),
        MarketplaceItem(id=1, user_id=2, title='Beta item'),
        MarketplaceItem(id=2, user_id=3, title='Alpha item'),
        Confession(id=1, user_id=2, college_domain='beta.ac.in', content='Private', scope='college'),
        Confession(id=2, user_id=2, college_domain='beta.ac.in', content='Global', scope='global'),
        Confession(id=3, user_id=3, college_domain='alpha.ac.in', content='Same college', scope='college'),
    ])
    session.commit()
    yield session
    session.close()
    engine.dispose()


def student(id=1, admin=False):
    domain = 'beta.ac.in' if id == 2 else 'alpha.ac.in'
    return AuthenticatedUser(id, f's{id}@{domain}', domain, True, admin)


def rejected(call):
    with pytest.raises(HTTPException) as error:
        call()
    return error.value.status_code


@pytest.mark.parametrize('by_user', [False, True])
def test_foreign_profile_hidden_and_same_college_visible(db, by_user):
    endpoint = profiles.get_profile_by_user if by_user else profiles.get_profile
    assert rejected(lambda: endpoint(2 if by_user else 3, student(), db)) == 404
    assert endpoint(3 if by_user else 20, student(), db)['display_name'] == 'Three'
    assert endpoint(2 if by_user else 3, student(admin=True), db)['display_name'] == 'Two'


def test_profile_id_does_not_fall_back_to_user_id(db):
    assert profiles.get_profile(3, student(admin=True), db)['user_id'] == 2
    assert profiles.get_profile_by_user(3, student(), db)['user_id'] == 3


def test_foreign_marketplace_detail_and_interest_are_hidden(db):
    assert rejected(lambda: marketplace.get_marketplace_item(1, db, student())) == 404
    assert rejected(lambda: immediate(marketplace.toggle_interest(1, db, student()))) == 404
    assert db.query(MarketplaceInterest).count() == 0
    assert db.query(Notification).count() == 0


def test_same_college_interest_and_admin_access_continue_to_work(db):
    assert immediate(marketplace.toggle_interest(2, db, student()))['interested']
    assert immediate(marketplace.toggle_interest(1, db, student(admin=True)))['interested']


def test_private_foreign_confession_detail_and_like_are_hidden(db):
    assert rejected(lambda: immediate(confessions.get_confession(1, db, student()))) == 404
    assert rejected(lambda: immediate(confessions.toggle_like(1, db, student()))) == 404
    assert db.query(ConfessionLike).count() == 0
    assert db.query(Notification).count() == 0


def test_global_and_same_college_confessions_remain_accessible(db):
    for id in [2, 3]:
        assert immediate(confessions.get_confession(id, db, student())).id == id
        assert immediate(confessions.toggle_like(id, db, student()))['liked']
    assert immediate(confessions.toggle_like(1, db, student(admin=True)))['liked']


def test_expired_content_cannot_be_reacted_to_by_other_users(db):
    db.get(MarketplaceItem, 2).created_at = datetime.utcnow() - timedelta(days=15)
    db.get(Confession, 3).created_at = datetime.utcnow() - timedelta(hours=49)
    db.commit()
    assert rejected(lambda: immediate(marketplace.toggle_interest(2, db, student()))) == 404
    assert rejected(lambda: immediate(confessions.toggle_like(3, db, student()))) == 404


def credentials(db, id=1):
    user = db.get(User, id)
    sid, refresh = issue_session(db, user)
    access = auth.create_user_access_token(user, session_id=sid)
    return sid, access, refresh


def cookie(response):
    parsed = SimpleCookie()
    parsed.load(response.headers['set-cookie'])
    return parsed['refresh_token'].value


def test_logout_revokes_current_access_and_refresh_but_not_other_device(db):
    sid, access, refresh = credentials(db)
    _, other_access, other_refresh = credentials(db)
    assert authenticate_session(access, db).id == 1
    response = Response()
    auth.logout(response, refresh, None, db)
    assert 'Max-Age=0' in response.headers['set-cookie']
    assert rejected(lambda: authenticate_session(access, db)) == 401
    assert rejected(lambda: auth.refresh_token(Response(), refresh, db)) == 401
    assert authenticate_session(other_access, db).id == 1
    assert auth.refresh_token(Response(), other_refresh, db)['access_token']


def test_bearer_only_logout_revokes_the_session(db):
    _, access, refresh = credentials(db)
    auth.logout(Response(), None, 'Bearer ' + access, db)
    assert rejected(lambda: authenticate_session(access, db)) == 401
    assert rejected(lambda: auth.refresh_token(Response(), refresh, db)) == 401


def test_refresh_rotates_single_use_token_and_replay_revokes_family(db):
    _, access, refresh = credentials(db)
    response = Response()
    updated = auth.refresh_token(response, refresh, db)
    next_refresh = cookie(response)
    assert refresh != next_refresh
    assert authenticate_session(updated['access_token'], db).id == 1
    assert rejected(lambda: auth.refresh_token(Response(), refresh, db)) == 401
    assert rejected(lambda: auth.refresh_token(Response(), next_refresh, db)) == 401
    assert rejected(lambda: authenticate_session(access, db)) == 401


def test_rotated_refresh_token_can_refresh_normally(db):
    _, _, refresh = credentials(db)
    response = Response()
    auth.refresh_token(response, refresh, db)
    assert auth.refresh_token(Response(), cookie(response), db)['access_token']


def test_password_reset_revokes_all_devices_but_not_another_user(db):
    _, access1, refresh1 = credentials(db)
    _, access2, refresh2 = credentials(db)
    _, other_access, _ = credentials(db, 3)
    redis = SimpleNamespace(get=AsyncMock(return_value=json.dumps({'otp': '123456', 'attempts': 0})), delete=AsyncMock())
    payload = ResetPasswordRequest(email='one@alpha.ac.in', otp='123456', new_password='AnewSecurePass123!')
    immediate(auth.reset_password(payload, db, redis))
    for access, refresh in [(access1, refresh1), (access2, refresh2)]:
        assert rejected(lambda: authenticate_session(access, db)) == 401
        assert rejected(lambda: auth.refresh_token(Response(), refresh, db)) == 401
    assert authenticate_session(other_access, db).id == 3
    assert security.verify_password(payload.new_password, db.get(User, 1).password_hash)


def test_legacy_tokens_require_login_again(db):
    user = db.get(User, 1)
    assert rejected(lambda: authenticate_session(auth.create_user_access_token(user), db)) == 401
    legacy_refresh = security.create_refresh_token('1')
    assert rejected(lambda: auth.refresh_token(Response(), legacy_refresh, db)) == 401


def test_expired_session_rejects_access_and_refresh(db):
    sid, access, refresh = credentials(db)
    db.get(AuthSession, sid).expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    assert rejected(lambda: authenticate_session(access, db)) == 401
    assert rejected(lambda: auth.refresh_token(Response(), refresh, db)) == 401


def test_new_login_creates_an_authorized_session(db):
    db.get(User, 1).password_hash = security.get_password_hash('password123')
    db.commit()
    form = OAuth2PasswordRequestForm(username='one@alpha.ac.in', password='password123')
    response = Response()
    result = auth.login(response, form, db)
    assert authenticate_session(result['access_token'], db).id == 1
    assert auth.refresh_token(Response(), cookie(response), db)['access_token']


def test_google_login_creates_an_authorized_session(db):
    response = Response()
    info = {'email': 'one@alpha.ac.in', 'aud': settings.GOOGLE_CLIENT_ID, 'email_verified': True}
    with patch('app.api.auth.google_id_token.verify_oauth2_token', return_value=info):
        result = auth.google_login(GoogleLoginRequest(credential='test-token'), response, db)
    assert authenticate_session(result['access_token'], db).id == 1
    assert auth.refresh_token(Response(), cookie(response), db)['access_token']


def test_verified_registration_creates_an_authorized_session(db):
    redis = SimpleNamespace(
        get=AsyncMock(return_value=json.dumps({'email': 'new@alpha.ac.in', 'password_hash': 'hash', 'otp': '123456'})),
        delete=AsyncMock(),
    )
    response = Response()
    result = immediate(auth.verify_registration(VerifyRegistrationRequest(pending_id='pending', otp='123456'), response, db, redis))
    assert authenticate_session(result['access_token'], db).email == 'new@alpha.ac.in'
    assert auth.refresh_token(Response(), cookie(response), db)['access_token']


def test_websocket_delivery_rejects_a_revoked_session(db):
    _, access, refresh = credentials(db)
    auth.logout(Response(), refresh, None, db)
    socket = SimpleNamespace(state=SimpleNamespace(auth_token=access), send_text=AsyncMock(), close=AsyncMock())
    manager = chat.ConnectionManager()
    manager.active_connections[1] = [socket]
    with patch('app.api.chat.SessionLocal', return_value=db):
        immediate(manager.send_personal_message('{"content":"private"}', 1))
    socket.send_text.assert_not_called()
    socket.close.assert_awaited_once_with(code=1008)
    assert 1 not in manager.active_connections
