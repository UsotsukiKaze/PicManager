import hashlib
import hmac
import time
from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import schemas
from app.models import AgeAssertionNonce, AgeAuthorizationRequest, GroupAgeSetting
from app.routers.integrations import bot as bot_routes
from app.services import ImageService


def test_age_rating_ceiling_is_inclusive():
    assert ImageService.allowed_age_ratings("all") == ("all",)
    assert ImageService.allowed_age_ratings("r12") == ("all", "r12")
    assert ImageService.allowed_age_ratings("r16") == ("all", "r12", "r16")
    assert ImageService.allowed_age_ratings("r18") == ("all", "r12", "r16", "r18")


def _sign(secret, action, subject_id, role, target, timestamp, nonce):
    message = "|".join((action, subject_id, role, target, str(timestamp), nonce))
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def test_r18_approval_is_persisted_by_picmanager(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    GroupAgeSetting.__table__.create(engine)
    AgeAuthorizationRequest.__table__.create(engine)
    AgeAssertionNonce.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    request_id = "request-1"
    secret = "dedicated-assertion-secret"
    reviewer_id = "123456"

    with sessions() as db:
        db.add(AgeAuthorizationRequest(
            request_id=request_id,
            group_id="98765",
            requested_by="222",
        ))
        db.commit()

    @contextmanager
    def database_context():
        db = sessions()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    monkeypatch.setattr(bot_routes, "get_db_context", database_context)
    monkeypatch.setattr(bot_routes.settings, "AGE_RATING_ASSERTION_SECRET", secret)
    monkeypatch.setattr(bot_routes.settings, "AGE_RATING_SUPERUSERS", reviewer_id)
    timestamp = int(time.time())
    nonce = "a" * 32

    result = bot_routes.approve_bot_age_authorization(
        request_id,
        schemas.BotAgeAuthorizationDecision(
            reviewer_id=reviewer_id,
            timestamp=timestamp,
            nonce=nonce,
            signature=_sign(secret, "approve_r18", reviewer_id, "superuser", request_id, timestamp, nonce),
        ),
    )

    assert result["status"] == "approved"
    with sessions() as db:
        setting = db.query(GroupAgeSetting).filter_by(group_id="98765").one()
        assert setting.age_rating == "r18"


def test_age_assertion_cannot_be_replayed(monkeypatch):
    secret = "dedicated-assertion-secret"
    timestamp = int(time.time())
    nonce = "b" * 32
    signature = _sign(secret, "approve_r18", "1", "superuser", "request", timestamp, nonce)
    monkeypatch.setattr(bot_routes.settings, "AGE_RATING_ASSERTION_SECRET", secret)
    engine = create_engine("sqlite:///:memory:")
    AgeAssertionNonce.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        bot_routes._verify_age_assertion(
            "approve_r18", "1", "superuser", "request", timestamp, nonce, signature, db
        )
        db.commit()
    with sessions() as db, pytest.raises(HTTPException) as exc:
        bot_routes._verify_age_assertion(
            "approve_r18", "1", "superuser", "request", timestamp, nonce, signature, db
        )
    assert exc.value.status_code == 401
