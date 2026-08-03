from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import schemas
from app.models import LoginTicket, User, UserRole
from app.routers.integrations import bot as bot_routes


def test_bot_ticket_refreshes_existing_root_identity(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    User.__table__.create(engine)
    LoginTicket.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)
    qq_number = '123456789'

    with session_factory() as db:
        db.add(User(qq_number=qq_number, role=UserRole.ROOT.value, nickname='root'))
        db.commit()

    @contextmanager
    def database_context():
        db = session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(bot_routes, 'get_db_context', database_context)
    monkeypatch.setattr(bot_routes.settings, 'ROOT_QQ', qq_number)
    monkeypatch.setattr(bot_routes.settings, 'PHROLOVA_PUBLIC_BASE_URL', 'https://game.example')

    bot_routes.create_bot_login_ticket(schemas.BotLoginTicketCreate(
        qq_number=qq_number,
        purpose='phrolova',
        nickname='最新昵称',
        avatar_url='https://q1.qlogo.cn/avatar?v=2',
    ))

    with session_factory() as db:
        user = db.query(User).filter(User.qq_number == qq_number).one()
        assert user.role == UserRole.ROOT.value
        assert user.nickname == '最新昵称'
        assert user.avatar_url == 'https://q1.qlogo.cn/avatar?v=2'
