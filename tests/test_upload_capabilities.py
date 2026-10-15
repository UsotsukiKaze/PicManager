from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.public_api import uploads


def test_upload_capabilities_follow_server_configuration_and_require_session(monkeypatch):
    @contextmanager
    def fake_db():
        yield object()

    monkeypatch.setattr(uploads, 'get_db_context', fake_db)
    monkeypatch.setattr(uploads, 'get_current_session', lambda request, db: None)
    app = FastAPI()
    app.include_router(uploads.router)
    client = TestClient(app)
    assert client.get('/upload/capabilities').status_code == 401
    monkeypatch.setattr(uploads, 'get_current_session', lambda request, db: {'is_guest': True})
    monkeypatch.setattr(uploads.settings, 'MAX_FILE_SIZE', 12345)
    monkeypatch.setattr(uploads.settings, 'ALLOWED_EXTENSIONS', ['.PNG', 'jpg'])
    response = client.get('/upload/capabilities')
    assert response.status_code == 200
    assert response.json() == {'max_file_size': 12345, 'extensions': ['jpg', 'png']}
