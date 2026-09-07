from collections.abc import Iterable


CONTRIBUTION_WEIGHTS = {
    "add": 3,
    "edit": 1,
}


def calculate_contribution_score(request_types: Iterable[str]) -> int:
    """Calculate a contribution score from approved request types."""
    return sum(CONTRIBUTION_WEIGHTS.get(request_type, 0) for request_type in request_types)
