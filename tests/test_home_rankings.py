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


def test_character_and_group_rankings_use_available_inventory_not_traffic(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    first, second, empty = [models.Group(name=name) for name in ('A', 'B', 'Empty')]
    session.add_all([first, second, empty]); session.flush()
    a = models.Character(name='A1', group_id=first.id)
    b = models.Character(name='A2', group_id=first.id)
    c = models.Character(name='B1', group_id=second.id)
    unused = models.Character(name='Unused', group_id=first.id)
    session.add_all([a, b, c, unused]); session.flush()
    for n, (group, roles, status) in enumerate([
        (first, [a, b], 'available'), (first, [a], 'available'),
        (second, [c], 'available'), (second, [c], 'available'), (second, [c], 'available'),
        (first, [unused], 'archived'), (first, [unused], 'missing'),
    ]):
        session.add(models.Image(image_id=f'{n:010}', file_extension='jpg', file_path=f'{n}.jpg',
                                 groups=[group], characters=roles, file_status=status))
    session.add(models.CharacterQueryCount(character_id=unused.id, query_count=999999))
    session.commit()
    @contextmanager
    def context():
        yield session
    monkeypatch.setattr(rankings, 'get_db_context', context)
    rankings._RANKINGS_CACHE.update(key=None, expires_at=0, data=None)
    result = rankings.get_rankings(10)
    assert [(row['name'], row['image_count']) for row in result['characters']] == [
        ('B1', 3), ('A1', 2), ('A2', 1), ('Unused', 0)]
    assert [(row['name'], row['character_count'], row['image_count']) for row in result['groups']] == [
        ('B', 1, 3), ('A', 3, 2), ('Empty', 0, 0)]
    assert len(rankings.get_rankings(1)['characters']) == 1
    # Filter before limiting, including roles outside the global top result.
    filtered = rankings.get_rankings(1, group_id=first.id)
    assert [(row['name'], row['image_count']) for row in filtered['characters']] == [('A1', 2)]
    assert filtered['groups'] == rankings.get_rankings(1)['groups']
    assert rankings.get_rankings(1)['characters'][0]['name'] == 'B1'
    assert [row['name'] for row in rankings.get_rankings(10, group_id=first.id)['characters']] == ['A1', 'A2', 'Unused']
    assert rankings.get_rankings(10, group_id=empty.id)['characters'] == []
    assert rankings.get_rankings(10, group_id=999999)['characters'] == []
    session.close(); engine.dispose()
