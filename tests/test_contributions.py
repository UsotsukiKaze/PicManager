from app.contributions import CONTRIBUTION_WEIGHTS, calculate_contribution_score


def test_contribution_weights_use_profile_scoring_rules():
    assert CONTRIBUTION_WEIGHTS == {"add": 3, "edit": 1}


def test_calculate_contribution_score_ignores_unscored_request_types():
    request_types = ["add", "add", "edit", "delete", "group_add"]

    assert calculate_contribution_score(request_types) == 7
