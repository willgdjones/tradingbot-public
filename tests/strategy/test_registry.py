"""Strategy registry behavior."""

from __future__ import annotations

import pytest

from tradingbot.strategy import get_strategy, registered
from tradingbot.strategy.examples import ThresholdMaker
from tradingbot.strategy.interface import Strategy
from tradingbot.strategy.registry import register


def test_reference_strategy_is_registered_on_import():
    assert registered()[ThresholdMaker.key] is ThresholdMaker
    assert get_strategy(ThresholdMaker.key) is ThresholdMaker


def test_unknown_key_raises_with_a_helpful_message():
    with pytest.raises(KeyError, match="no strategy registered"):
        get_strategy("does-not-exist")


def test_registering_a_conflicting_key_is_rejected():
    class Clash(Strategy):
        key = ThresholdMaker.key

        def on_event(self, ctx, event):
            return []

    with pytest.raises(ValueError, match="already registered"):
        register(Clash)


def test_re_registering_the_same_class_is_idempotent():
    assert register(ThresholdMaker) is ThresholdMaker
