import pytest
from fastapi import HTTPException

from app.routers.public_api.characters import _validate_managed_avatar as validate_character_avatar
from app.routers.public_api.groups import _validate_managed_avatar as validate_group_avatar


@pytest.mark.parametrize("validator", [validate_group_avatar, validate_character_avatar])
def test_entity_avatar_paths_must_be_managed_webp_files(validator):
    validator(None)
    validator("/resource/avatars/0123456789abcdef0123456789abcdef.webp")

    with pytest.raises(HTTPException):
        validator("https://example.com/avatar.png")
    with pytest.raises(HTTPException):
        validator("/resource/avatars/../store/private.jpg")
