from app.services.squad_rating import _get_regression_flag
from app.models.player import Player, Position


def make_fake_player(position):
    return Player(
        id=9999,
        team_id=9999,
        first_name="Fake",
        second_name="Player",
        web_name="Fake",
        position=position,
    )


def test_flag_fires_when_both_conditions_hold():
    player = make_fake_player(Position.DEF)
    flag = _get_regression_flag(player, stats=None, score_percentile=80, xgc_ease_by_id={9999: 30})
    assert flag is not None


def test_flag_absent_when_only_score_is_high():
    player = make_fake_player(Position.DEF)
    flag = _get_regression_flag(player, stats=None, score_percentile=80, xgc_ease_by_id={9999: 60})
    assert flag is None


def test_flag_absent_when_only_xgc_is_bad():
    player = make_fake_player(Position.DEF)
    flag = _get_regression_flag(player, stats=None, score_percentile=50, xgc_ease_by_id={9999: 30})
    assert flag is None


def test_flag_never_fires_for_attacking_positions():
    player = make_fake_player(Position.FWD)
    flag = _get_regression_flag(player, stats=None, score_percentile=99, xgc_ease_by_id={9999: 5})
    assert flag is None
