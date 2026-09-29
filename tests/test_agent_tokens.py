"""Exercise credential lifecycle and negative authorization through the real API."""
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.database import get_session
from app.main import app
from app.models.agent_token import AgentToken
from app.models.user import User
from app.models.user_signal import UserSignal


@pytest.fixture
def client_and_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine, tables=[User.__table__, UserSignal.__table__, AgentToken.__table__])
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE events (id INTEGER PRIMARY KEY, tags JSON)"))
    def session():
        with Session(engine) as instance:
            yield instance
    app.dependency_overrides[get_session] = session
    try:
        with TestClient(app) as client:
            yield client, engine
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()


def _owner(client, email='owner@example.com'):
    result = client.post('/auth/register', json={'email': email, 'password': 'correct horse battery'} )
    assert result.status_code == 201, result.text
    return {'Authorization': 'Bearer ' + result.json()['access_token']}


def _mint(client, owner, scopes=None):
    response = client.post('/users/me/tokens', headers=owner, json={'name': 'MCP read',
        'scopes': scopes or ['events:read', 'profile:read']})
    assert response.status_code == 201, response.text
    assert response.headers['cache-control'] == 'private, no-store'
    return response.json()


def _bearer(token):
    return {'Authorization': 'Bearer ' + token['token']}


def test_mint_use_inspect_revoke_without_sharing_a_password(client_and_db):
    client, engine = client_and_db
    owner = _owner(client)
    token = _mint(client, owner)
    assert token['token'].startswith('tof_pat_')
    with Session(engine) as session:
        row = session.get(AgentToken, token['id'])
        assert row.token_hash == hashlib.sha256(token['token'].encode()).hexdigest()
        assert token['token'] not in repr(row)
    response = client.get('/users/me', headers=_bearer(token))
    assert response.status_code == 200, response.text
    assert 'hashed_password' not in response.text and 'email' not in response.json()
    metadata = client.get('/users/me/tokens', headers=owner)
    assert metadata.status_code == 200
    assert metadata.headers['cache-control'] == 'private, no-store'
    assert metadata.json()[0]['request_count'] == 1
    assert metadata.json()[0]['last_used_at'] is not None
    assert 'token' not in metadata.json()[0] and 'token_hash' not in metadata.text
    assert client.delete('/users/me/tokens/'+str(token['id']), headers=owner).status_code == 204
    assert client.get('/users/me', headers=_bearer(token)).status_code == 401
    assert client.delete('/users/me/tokens/'+str(token['id']), headers=owner).status_code == 204


@pytest.mark.parametrize('method,path,payload', [
    ('post','/users/me/tokens', {'name':'escalate','scopes':['events:read']}),
    ('get','/users/me/tokens', None),
    ('delete','/users/me/tokens/1', None),
    ('put','/users/me/preferences', {'preferred_vibes':['#calm']}),
    ('post','/users/me/onboarding', {'perfect_saturday':'quiet fun'}),
    ('post','/concierge/itinerary/share', {'publish_publicly': True, 'stops': []}),
    ('post','/folders', {'name':'a public folder'}),
])
def test_agent_cannot_reach_human_authority_routes(client_and_db, method, path, payload):
    client, _ = client_and_db
    token = _mint(client, _owner(client), ['events:read','profile:read','signals:write','plans:read'])
    response = client.request(method, path, headers=_bearer(token), json=payload)
    assert response.status_code == 401, response.text


def test_pat_cannot_access_internal_provider_credentials(client_and_db, monkeypatch):
    from app.core.config import Settings, get_settings
    client, _ = client_and_db
    token = _mint(client, _owner(client))
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, aaim_enabled=True, aaim_jwt_shared_secret='separate-internal-key')
    try:
        assert client.get('/internal/secrets/ticketmaster/active-key', headers=_bearer(token)).status_code == 401
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_read_only_token_cannot_write_signals_and_scopes_cannot_escalate(client_and_db):
    client, _ = client_and_db
    owner = _owner(client)
    token = _mint(client, owner)
    assert client.post('/users/me/interests', headers=_bearer(token),
        json={'action':'like', 'vibe_tag':'#calm'}).status_code == 403
    for scopes in [['*'], ['internal:secrets:read'], ['profile:write'], []]:
        assert client.post('/users/me/tokens', headers=owner,
            json={'name':'bad','scopes':scopes}).status_code == 422


def test_delegated_signals_retain_token_provenance(client_and_db):
    client, engine = client_and_db
    owner = _owner(client)
    token = _mint(client, owner, ['profile:read','signals:write'])
    response = client.post('/users/me/interests', headers=_bearer(token), json={'action':'like','vibe_tag':'#calm'})
    assert response.status_code == 200, response.text
    assert client.post('/users/me/interests', headers=owner, json={'action':'like','vibe_tag':'#social'}).status_code == 200
    with Session(engine) as session:
        rows = session.exec(select(UserSignal).order_by(UserSignal.id)).all()
        assert [row.created_via for row in rows] == [f'agent:{token["id"]}', 'user']
        assert all(row.user_id == response.json()['user_id'] for row in rows)


def test_wrong_secret_expiry_deactivation_and_wrong_owner_fail_closed(client_and_db):
    client, engine = client_and_db
    owner = _owner(client)
    other = _owner(client, 'other@example.com')
    token = _mint(client, owner)
    assert client.get('/users/me/tokens', headers=other).json() == []
    assert client.delete('/users/me/tokens/'+str(token['id']), headers=other).status_code == 404
    altered = dict(token, token=token['token'][:-1] + ('X' if token['token'][-1] != 'X' else 'Y'))
    assert client.get('/users/me', headers=_bearer(altered)).status_code == 401
    for raw in ['tof_pat_wrong', 'tof_pat_'+'0'*12+'_'+'a'*43, token['token']+' extra']:
        assert client.get('/users/me', headers={'Authorization':'Bearer '+raw}).status_code == 401
    with Session(engine) as session:
        row = session.get(AgentToken, token['id'])
        row.expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
        session.add(row); session.commit()
    assert client.get('/users/me', headers=_bearer(token)).status_code == 401
    with Session(engine) as session:
        row = session.get(AgentToken, token['id'])
        row.expires_at = datetime.now(timezone.utc)+timedelta(days=1)
        user = session.get(User, row.user_id); user.is_active = False
        session.add(row); session.add(user); session.commit()
    assert client.get('/users/me', headers=_bearer(token)).status_code == 403


def test_events_only_token_cannot_read_private_profile(client_and_db):
    client, _ = client_and_db
    token = _mint(client, _owner(client), ['events:read'])
    assert client.get('/users/me', headers=_bearer(token)).status_code == 403
    assert client.get('/recommendations', headers=_bearer(token)).status_code == 403


def test_agent_rate_limit_is_keyed_by_token_and_preserves_usage(client_and_db, monkeypatch):
    from app.core.security import _agent_limiter
    client, engine = client_and_db
    monkeypatch.setattr(_agent_limiter, 'limit', 2)
    token = _mint(client, _owner(client))
    assert client.get('/users/me', headers=_bearer(token)).status_code == 200
    assert client.get('/users/me', headers=_bearer(token)).status_code == 200
    response = client.get('/users/me', headers=_bearer(token))
    assert response.status_code == 429
    assert int(response.headers['retry-after']) > 0
    with Session(engine) as session:
        assert session.get(AgentToken, token['id']).request_count == 2
