"""Atlas ccxt adapter.

Normal çalışmada gerçek `ccxt` paketini kullanır.
Test/çevrimdışı senaryolarda mock implementasyona düşer.
"""

import importlib
import os
import sys
from pathlib import Path


def _running_under_pytest():
    if "PYTEST_CURRENT_TEST" in os.environ:
        return True
    return any("pytest" in arg for arg in sys.argv)


def _load_real_ccxt_module():
    repo_root = str(Path(__file__).resolve().parent)
    current_module = sys.modules.get(__name__)
    original_sys_path = list(sys.path)

    # Repo kökündeki mock modüllerin gerçek paketlerin önüne geçmesini önle.
    # "requests" gibi stdlib adlarını taşıyan yerel dosyalar ccxt içindeki
    # HTTP çağrılarını kırabileceğinden, import öncesinde önbelleği temizle.
    _shadowed_mods = {}
    for _mod_name in ("requests",):
        _existing = sys.modules.get(_mod_name)
        if _existing is not None:
            _mod_file = getattr(_existing, "__file__", None) or ""
            if str(Path(_mod_file).resolve()).startswith(repo_root):
                # Sahte (repo-içi) modülü geçici olarak kaldır
                _shadowed_mods[_mod_name] = sys.modules.pop(_mod_name)

    # Kendi modül gölgelemesini devre dışı bırakıp gerçek ccxt'yi yükle.
    sys.modules.pop("ccxt", None)
    try:
        sys.path = [
            path for path in original_sys_path
            if str(Path(path or ".").resolve()) != repo_root
        ]
        return importlib.import_module("ccxt")
    except Exception:
        # Yükleme başarısız olursa sahte modülleri geri koy
        sys.modules.update(_shadowed_mods)
        return None
    finally:
        sys.path = original_sys_path
        if current_module is not None:
            sys.modules["ccxt"] = current_module
        # Gerçek ccxt başarıyla yüklendiyse sahte requests'i geri yükleme;
        # sys.modules["requests"] artık gerçek paketi gösteriyor.


_mode = os.environ.get("ATLAS_CCXT_MODE", "auto").strip().lower()
_prefer_real = _mode == "real" or (_mode == "auto" and not _running_under_pytest())
_real_ccxt = _load_real_ccxt_module() if _prefer_real else None
_is_real_backend = _real_ccxt is not None and hasattr(_real_ccxt, "bybit")

if _mode == "real" and not _is_real_backend:
    raise ImportError(
        "ATLAS_CCXT_MODE=real set but real ccxt is unavailable. Install ccxt in the active environment."
    )

BACKEND = "real" if _is_real_backend else "mock"


if _is_real_backend:
    bybit = _real_ccxt.bybit
else:
    MOCK_SYMBOLS = [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
        "XRP/USDT:USDT",
        "BNB/USDT:USDT",
        "DOGE/USDT:USDT",
        "ADA/USDT:USDT",
        "AVAX/USDT:USDT",
        "TRX/USDT:USDT",
        "LINK/USDT:USDT",
        "DOT/USDT:USDT",
        "MATIC/USDT:USDT",
        "LTC/USDT:USDT",
        "BCH/USDT:USDT",
        "UNI/USDT:USDT",
        "NEAR/USDT:USDT",
        "ATOM/USDT:USDT",
        "APT/USDT:USDT",
        "OP/USDT:USDT",
        "ARB/USDT:USDT",
        "SUI/USDT:USDT",
        "SEI/USDT:USDT",
        "TIA/USDT:USDT",
        "PEPE/USDT:USDT",
        "WIF/USDT:USDT",
        "INJ/USDT:USDT",
        "AAVE/USDT:USDT",
        "FIL/USDT:USDT",
        "ETC/USDT:USDT",
        "XLM/USDT:USDT",
        "HBAR/USDT:USDT",
        "IMX/USDT:USDT",
        "RNDR/USDT:USDT",
        "RUNE/USDT:USDT",
        "GRT/USDT:USDT",
        "PYTH/USDT:USDT",
    ]

    class bybit:
        """Small subset of ccxt.bybit used by offline smoke tests."""

        def __init__(self, config=None):
            self.config = config or {}

        def load_markets(self):
            return {
                symbol: {
                    "active": True,
                    "swap": True,
                    "quote": "USDT",
                }
                for symbol in MOCK_SYMBOLS
            }

        def fetch_ohlcv(self, symbol, timeframe="15m", since=None, limit=100):
            base_time = 1_700_000_000_000
            step_ms = self._timeframe_to_ms(timeframe)
            symbol_seed = sum(ord(char) for char in symbol)
            if symbol.startswith("BTC"):
                base_price = 100_000.0
            elif symbol.startswith("ETH"):
                base_price = 3_000.0
            else:
                base_price = 50.0 + float(symbol_seed % 4_000)
            rows = []

            for i in range(limit or 100):
                wave = (i % 20) - 10
                trend = i * (1.8 + ((symbol_seed % 17) / 20))
                open_price = base_price + trend + (wave * 12)
                close_price = open_price + (18 if i % 2 == 0 else -14)
                high = max(open_price, close_price) + 35 + (i % 5)
                low = min(open_price, close_price) - 35 - (i % 7)
                volume = 100 + (i % 30)
                rows.append([
                    base_time + (i * step_ms),
                    float(open_price),
                    float(high),
                    float(low),
                    float(close_price),
                    float(volume),
                ])

            return rows

        def _timeframe_to_ms(self, timeframe):
            mapping = {
                "15m": 15 * 60 * 1000,
                "4h": 4 * 60 * 60 * 1000,
                "1d": 24 * 60 * 60 * 1000,
                "1w": 7 * 24 * 60 * 60 * 1000,
            }
            return mapping.get(timeframe, mapping["15m"])
