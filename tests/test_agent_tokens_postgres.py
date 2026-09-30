"""Exact API lifecycle and admission concurrency on disposable PostgreSQL."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlmodel import Session, select

from app.core.database import get_session
from app.main import app
from app.models.agent_token import AgentToken
from app.models.user import User
from conftest import _require_disposable_database


def test_concurrent_admissions_survive_sessions_and_revocation():
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Disposable TEST_DATABASE_URL required')
    _require_disposable_database(url)
    engine = create_engine(url)
    owner_id = None
    def session():
        with Session(engine) as instance:
            yield instance
    app.dependency_overrides[get_session] = session
    try:
        with TestClient(app) as client:
            auth = client.post('/auth/register', json={'email': f'{uuid4().hex}@example.com', 'password':'test password for owner'})
            assert auth.status_code == 201, auth.text
            owner_id = auth.json()['user_id']
            owner = {'Authorization':'Bearer '+auth.json()['access_token']}
            minted = client.post('/users/me/tokens', headers=owner,
                json={'name':'concurrent MCP', 'scopes':['events:read','profile:read']})
            assert minted.status_code == 201, minted.text
            token = minted.json()
            agent = {'Authorization':'Bearer '+token['token']}
            def read(_):
                return client.get('/users/me', headers=agent).status_code
            with ThreadPoolExecutor(max_workers=6) as pool:
                assert list(pool.map(read, range(24))) == [200]*24
            with Session(engine) as instance:
                row = instance.get(AgentToken, token['id'])
                assert row.request_count == 24
                assert row.last_used_at is not None
            assert client.get('/events?limit=1', headers=agent).status_code == 200
            assert client.get('/recommendations?limit=1', headers=agent).status_code == 200
            assert client.delete('/users/me/tokens/'+str(token['id']), headers=owner).status_code == 204
            assert client.get('/events?limit=1', headers=agent).status_code == 401
            assert client.get('/recommendations?limit=1', headers=agent).status_code == 401
            # Revoking scoped access does not change deliberately anonymous public discovery.
            assert client.get('/events?limit=1').status_code == 200
    finally:
        app.dependency_overrides.pop(get_session, None)
        if owner_id:
            with engine.begin() as connection:
                connection.execute(delete(AgentToken).where(AgentToken.user_id == owner_id))
                connection.execute(delete(User).where(User.id == owner_id))
        engine.dispose()


def test_public_stale_jwt_fallback_and_events_only_planning_privacy(monkeypatch):
    from datetime import datetime, timedelta, timezone
    import jwt
    from app.api import discovery
    from app.core.config import get_settings
    from app.core.localtime import LOCAL_TZ
    from app.models.event import Event
    from app.services.concierge import parse_intent_prompt
    from test_event_detail_api import _build_client

    async def parse(query):
        return parse_intent_prompt(query)
    monkeypatch.setattr(discovery, 'parse_intent_async', parse)
    calls = []
    def profile(**kwargs):
        calls.append(kwargs['user_id'])
        return {}
    monkeypatch.setattr(discovery._user_profile_service, 'compute_vibe_scores_for_user', profile)
    with _build_client() as (client, session):
        auth = client.post('/auth/register', json={'email':f'{uuid4().hex}@example.com','password':'test stale JWT password'})
        assert auth.status_code == 201
        owner = {'Authorization':'Bearer '+auth.json()['access_token']}
        start = (datetime.now(LOCAL_TZ)+timedelta(days=1)).replace(hour=19,minute=0,second=0,microsecond=0)
        event = Event(title='Token privacy anchor',start_at=start,source_name='fixture',source_tier=1,
            location='POINT(-122.4 37.7)',tags=['#date'])
        session.add(event);session.flush()
        expired = jwt.encode({'sub': 'expired@example.com', 'exp': datetime.now(timezone.utc)-timedelta(seconds=1)}, get_settings().jwt_secret_key, algorithm='HS256')
        for raw in [expired, 'invalid-JWT']:
            headers = {'Authorization':'Bearer '+raw}
            assert client.get('/events', headers=headers).status_code == 200
            assert client.get(f'/events/{event.id}', headers=headers).status_code == 200
            assert client.post('/concierge/itinerary', headers=headers, json={'query':'date night tomorrow'}).status_code == 200
        assert calls == []
        for scopes in [['events:read'],['events:read','profile:read']]:
            mint = client.post('/users/me/tokens', headers=owner,json={'name':'privacy','scopes':scopes})
            assert mint.status_code == 201
            headers = {'Authorization':'Bearer '+mint.json()['token']}
            result = client.post('/concierge/itinerary',headers=headers,json={'query':'date night tomorrow'})
            assert result.status_code == 200, result.text
            assert result.json()['anchor_event_id'] is not None
            if 'profile:read' not in scopes:
                assert calls == []
        assert calls == [auth.json()['user_id']]
