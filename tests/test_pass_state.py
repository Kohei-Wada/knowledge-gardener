import time

from recap.shared import pass_state


def test_nothing_recorded_before_the_first_pass():
    assert pass_state.last_pass_started("aaaaaaaa") is None
    assert pass_state.covered_until("aaaaaaaa") is None


def test_a_failed_pass_throttles_without_covering_anything():
    started = time.time() - 100
    pass_state.mark_pass_started("aaaaaaaa", started)
    assert abs(pass_state.last_pass_started("aaaaaaaa") - started) < 0.01
    assert pass_state.covered_until("aaaaaaaa") is None


def test_a_later_failed_pass_keeps_what_an_earlier_one_covered():
    pass_state.mark_covered("aaaaaaaa", 1000.5)
    pass_state.mark_pass_started("aaaaaaaa", 2000.0)
    assert pass_state.covered_until("aaaaaaaa") == 1000.5
    assert pass_state.last_pass_started("aaaaaaaa") == 2000.0
