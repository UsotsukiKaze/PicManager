import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import LoginTicket
from app.security.tickets import consume_login_ticket, create_login_ticket


def _session():
    engine = create_engine('sqlite:///:memory:')
    LoginTicket.__table__.create(engine)
    return sessionmaker(bind=engine)()


def test_phrolova_ticket_is_single_use():
    db = _session()
    issued = create_login_ticket(db, '123456789', purpose='phrolova')
    db.commit()

    consumed = consume_login_ticket(db, issued.ticket, purpose='phrolova')
    db.commit()

    assert consumed.used_at is not None
    with pytest.raises(HTTPException) as error:
        consume_login_ticket(db, issued.ticket, purpose='phrolova')
    assert error.value.status_code == 401


def test_phrolova_ticket_cannot_be_used_for_picmanager_login():
    db = _session()
    issued = create_login_ticket(db, '123456789', purpose='phrolova')
    db.commit()

    with pytest.raises(HTTPException) as error:
        consume_login_ticket(db, issued.ticket, purpose='login')

    assert error.value.status_code == 403
