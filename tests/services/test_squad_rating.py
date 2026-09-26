import pytest

from app.services.squad_rating import percentile_rank


def test_percentile_rank_middle_value():
    all_values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile_rank(3.0, all_values) == 40.0


def test_percentile_rank_highest_value():
    all_values = [1.0, 2.0, 3.0]
    assert percentile_rank(3.0, all_values) == pytest.approx(66.67, rel=1e-3)


def test_percentile_rank_lowest_value():
    all_values = [1.0, 2.0, 3.0]
    assert percentile_rank(1.0, all_values) == 0.0
