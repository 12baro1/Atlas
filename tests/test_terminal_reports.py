import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import atlas_tui


def test_performance_and_learning_commands_are_recognized():
    for command in ("performans", "istatistik", "öğrenme", "ogrenme durumu"):
        assert atlas_tui._is_supported_input(command)


def test_liquidity_command_parses_optional_symbol():
    assert atlas_tui._parse_liquidity_command("likidite") is None
    assert atlas_tui._parse_liquidity_command("likidite btc") == "BTC"
    assert atlas_tui._parse_liquidity_command("LİKİDİTE ETH/USDT:USDT") == "ETH/USDT:USDT"
    assert atlas_tui._parse_liquidity_command("likidite BTC USDT") is False


def test_performance_report_keeps_signal_and_manual_results_separate():
    app = object.__new__(atlas_tui.AtlasTUIApp)

    class Runtime:
        def signal_performance(self):
            return {"closed": 12, "wins": 7, "losses": 4, "partials": 1, "winrate": 58.3,
                    "expectancy": 0.22, "profit_factor": 1.4, "tp1": 8, "tp2": 3, "tp3": 1, "sl": 4}

        def manual_performance(self):
            return {"total": 3, "wins": 2, "losses": 1, "open": 1, "winrate": 66.7,
                    "expectancy": 0.5, "profit_factor": 2.0}

        def learning_panel(self):
            return {"source": "manual", "closed_manual_trades": 3, "matched_setups": 2,
                    "reliability": 0.4, "learning_adjustment": 0.1}

    app.runtime = Runtime()
    report = app._format_performance("performans")

    assert "OTOMATİK SİNYAL SONUÇLARI" in report
    assert "MANUEL İŞLEMLER" in report
    assert "Kapanan: 12" in report
    assert "Kapanan: 3" in report
    assert "20 kapanan işlemin altında" in report


def test_liquidity_report_shows_clusters_and_sweep_confirmation():
    app = object.__new__(atlas_tui.AtlasTUIApp)
    report = app._format_liquidity({
        "ok": True,
        "symbol": "BTC/USDT:USDT",
        "result": {
            "symbol": "BTC/USDT:USDT",
            "analysis": {
                "liquidity_layers": {
                    "bsl": [{"price": 70000, "touches": 3, "liquidity_kind": "SWING"}],
                    "ssl": [{"price": 68000, "touches": 2, "liquidity_kind": "INTERNAL"}],
                    "eqh": [{"price": 70000, "touches": 3}],
                    "eql": [],
                },
                "liquidity_sweep": {
                    "is_sweep": True, "direction": "BEARISH", "strength_score": 75,
                    "buy_side": True, "sell_side": False, "post_structure": {"confirmed": True},
                },
            },
        },
    })

    assert "70000" in report
    assert "BUY-SIDE LIQUIDITY / BSL" in report
    assert "BSL süpürüldü: EVET" in report
    assert "Sonraki yapı teyidi: VAR" in report
