"""Round-trip owned sharing on migrated disposable PostGIS."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, select

from app.api.auth import _create_access_token
from app.core.config import get_settings
from app.core.database import get_session
from app.main import app
from app.models.event import Event
from app.models.itinerary import SavedItinerary
from app.models.user import User


def test_postgres_share_lifecycle_persists_owned_private_snapshot():
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to a migrated disposable PostgreSQL')
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
                app.dependency_overrides[get_session] = lambda: session
                try:
                    user = User(email=f'sharing-{uuid4().hex}@example.com')
                    event = Event(
                        title='Sharing lifecycle fixture',
                        start_at=datetime.now(timezone.utc) + timedelta(days=1),
                        source_name='test', source_tier=1,
                        venue_name='The Chapel', raw_address='777 Valencia St, San Francisco, CA',
                        location='SRID=4326;POINT(-122.4214 37.7599)',
                    )
                    session.add(user)
                    session.add(event)
                    session.commit()
                    token = _create_access_token(user=user, settings=get_settings())
                    with TestClient(app) as client:
                        headers = {'Authorization': f'Bearer {token}'}
                        response = client.post('/concierge/itinerary/share', headers=headers, json={
                            'query':'private fixture query', 'expires_in_days':1,
                            'stops':[{'kind':'main_event', 'event_id':event.id}],
                        })
                        assert response.status_code == 200, response.text
                        body = response.json()
                        assert 'query' not in body and 'private fixture query' not in body['text']
                        saved = session.exec(select(SavedItinerary).where(SavedItinerary.share_token == body['share_token'])).one()
                        assert saved.query == '' and saved.user_id == user.id
                        assert saved.expires_at - saved.created_at == timedelta(days=1)
                        assert saved.expires_at.tzinfo is not None
                        public_url = f"/shared/itineraries/{body['share_token']}"
                        public = client.get(public_url)  # A cold, anonymous reader.
                        assert public.status_code == 200
                        assert public.json()['itinerary'][0]['lat'] == pytest.approx(37.7599)
                        listed = client.get('/users/me/itineraries', headers=headers).json()
                        assert [item['share_token'] for item in listed] == [body['share_token']]
                        revoked = client.delete(f"/users/me/itineraries/{body['share_token']}", headers=headers)
                        assert revoked.status_code == 204
                        assert client.get(public_url).status_code == 404
                finally:
                    app.dependency_overrides.pop(get_session, None)
            transaction.rollback()
    finally:
        engine.dispose()
