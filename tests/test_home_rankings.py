from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.routers.public_api import rankings


def test_rankings_count_recent_available_images_by_group(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    recent = datetime.utcnow() - timedelta(days=2)
    old = datetime.utcnow() - timedelta(days=45)
    first_group = models.Group(name="近期第一")
    second_group = models.Group(name="近期第二")
    session.add_all([first_group, second_group])
    session.flush()

    images = [
        models.Image(image_id="0000000001", file_extension="jpg", file_path="resource/store/1.jpg", created_at=recent),
        models.Image(image_id="0000000002", file_extension="jpg", file_path="resource/store/2.jpg", created_at=recent),
        models.Image(image_id="0000000003", file_extension="jpg", file_path="resource/store/3.jpg", created_at=recent),
        models.Image(image_id="0000000004", file_extension="jpg", file_path="resource/store/4.jpg", created_at=old),
        models.Image(
            image_id="0000000005",
            file_extension="jpg",
            file_path="resource/store/5.jpg",
            file_status="archived",
            created_at=recent,
        ),
    ]
    images[0].groups = [first_group]
    images[1].groups = [first_group]
    images[2].groups = [second_group]
    images[3].groups = [second_group]
    images[4].groups = [second_group]
    session.add_all(images)
    session.commit()

    @contextmanager
    def fake_db_context():
        yield session

    monkeypatch.setattr(rankings, "get_db_context", fake_db_context)
    rankings._RANKINGS_CACHE.update({"key": None, "expires_at": 0.0, "data": None})

    result = rankings.get_rankings(limit=5)

    assert result["recent_days"] == 30
    assert result["recent_groups"] == [
        {
            "group_id": first_group.id,
            "name": "近期第一",
            "avatar_url": "/favicon.ico",
            "count": 2,
        },
        {
            "group_id": second_group.id,
            "name": "近期第二",
            "avatar_url": "/favicon.ico",
            "count": 1,
        },
    ]
