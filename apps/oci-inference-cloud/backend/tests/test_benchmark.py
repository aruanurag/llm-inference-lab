from app.benchmark import percentile


def test_percentile_handles_empty_values() -> None:
    assert percentile([], 95) is None


def test_percentile_returns_expected_value_for_small_set() -> None:
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([1, 2, 3, 4, 5], 95) == 5
