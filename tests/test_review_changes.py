from app.review_changes import build_changes, changed_update_data


def test_changed_update_data_ignores_equivalent_lists_and_empty_optional_text():
    proposed = {
        "description": "",
        "character_ids": [3, 1, 3],
        "group_ids": [2],
    }
    original = {
        "description": None,
        "character_ids": [1, 3],
        "group_ids": [2],
    }

    assert changed_update_data(proposed, original) == {}


def test_changed_update_data_keeps_only_real_changes():
    proposed = {
        "name": "新角色名",
        "nicknames": ["别名 B", "别名 A"],
        "description": None,
    }
    original = {
        "name": "原角色名",
        "nicknames": ["别名 A", "别名 B"],
        "description": "原描述",
    }

    assert changed_update_data(proposed, original) == {
        "name": "新角色名",
        "description": None,
    }


def test_build_changes_contains_before_after_and_label():
    changes = build_changes(
        {"group_id": 8, "description": "相同"},
        {"group_id": 7, "description": "相同"},
        {"group_id": "所属分组", "description": "描述"},
    )

    assert changes == [
        {
            "field": "group_id",
            "label": "所属分组",
            "before": 7,
            "after": 8,
        }
    ]
