from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.services import CharacterService, GroupService, ImageService


def test_entity_avatars_default_and_custom_values_are_serialized():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    default_group = GroupService.create_group(
        session,
        schemas.GroupCreate(name="默认头像分组"),
    )
    custom_group = GroupService.create_group(
        session,
        schemas.GroupCreate(name="自定义头像分组", avatar_url="https://example.com/group.png"),
    )
    character = CharacterService.create_character(
        session,
        schemas.CharacterCreate(
            name="自定义头像角色",
            group_id=custom_group["id"],
            avatar_url="https://example.com/character.png",
        ),
    )

    assert default_group["avatar_url"] == "/favicon.ico"
    assert custom_group["avatar_url"] == "https://example.com/group.png"
    assert character["avatar_url"] == "https://example.com/character.png"

    reset_group = GroupService.update_group(
        session,
        custom_group["id"],
        schemas.GroupUpdate(avatar_url=None),
    )
    assert reset_group["avatar_url"] == "/favicon.ico"

    image = models.Image(
        image_id="0000000001",
        file_extension="jpg",
        file_path="resource/store/1.jpg",
    )
    session.add(image)
    image.groups = [session.get(models.Group, custom_group["id"])]
    image.characters = [session.get(models.Character, character["id"])]
    session.flush()

    serialized = ImageService.image_to_dict(image)
    assert serialized["groups"][0]["avatar_url"] == "/favicon.ico"
    assert serialized["characters"][0]["avatar_url"] == "https://example.com/character.png"
