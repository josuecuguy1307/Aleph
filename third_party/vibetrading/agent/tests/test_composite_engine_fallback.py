"""Tests for CompositeEngine fallback when an unknown symbol is encountered."""

from __future__ import annotations

import pytest

from backtest.engines.composite import CompositeEngine


class TestCompositeEngineFallback:
    """Verify that CompositeEngine does not crash on unknown symbols."""

    def test_unknown_symbol_round_size(self):
        """round_size for a symbol not in the original codes should not crash."""
        config = {"initial_cash": 100_000}
        engine = CompositeEngine(config, ["BTC-USDT", "ETH-USDT"])
        result = engine.round_size(1.0, 100.0)
        assert isinstance(result, float)
        assert result >= 0.0

    def test_unknown_symbol_calc_commission(self):
        """calc_commission for a symbol not in the original codes should not crash."""
        config = {"initial_cash": 100_000}
        engine = CompositeEngine(config, ["BTC-USDT"])
        fee = engine.calc_commission(1.0, 100.0, 1, True)
        assert isinstance(fee, float)
        assert fee >= 0.0

    def test_unknown_symbol_leverage(self):
        """_leverage_for_symbol for a symbol not in the original codes should not crash."""
        config = {"initial_cash": 100_000}
        engine = CompositeEngine(config, ["BTC-USDT"])
        lev = engine._leverage_for_symbol("UNKNOWN-SYMBOL")
        assert isinstance(lev, float)
        assert lev > 0

    def test_known_symbols_still_use_correct_engine(self):
        """Known symbols should still route to their dedicated sub-engine."""
        config = {"initial_cash": 100_000, "maker_rate": 0.001}
        engine = CompositeEngine(config, ["BTC-USDT", "ETH-USDT"])
        # BTC-USDT should use the crypto sub-engine (maker_rate=0.001 from config)
        fee = engine.calc_commission(1.0, 50000.0, 1, False)
        # Crypto maker rate is 0.0002 by default, but config overrides to 0.001
        assert fee == pytest.approx(1.0 * 50000.0 * 0.001)

    def test_empty_rule_engines_raises(self):
        """If somehow _rule_engines is empty, should raise ValueError."""
        config = {"initial_cash": 100_000}
        engine = CompositeEngine(config, ["BTC-USDT"])
        engine._rule_engines = {}
        with pytest.raises(ValueError, match="No sub-engines available"):
            engine._rule_for("UNKNOWN-SYMBOL")
