"""Local-only mobile web interface for Atlas.

Run with: python3 atlas_mobile.py
Open on the same Android device: http://127.0.0.1:8765
"""
from __future__ import annotations

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = int(os.environ.get("ATLAS_MOBILE_PORT", "8765"))
_runtime = None
_runtime_lock = threading.Lock()
_analysis_lock = threading.Lock()


def get_runtime():
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            # This interface is local-only and must never start notification services.
            os.environ["ATLAS_TELEGRAM_ENABLED"] = "0"
            os.environ["ATLAS_TELEGRAM_POLLING_ENABLED"] = "0"
            os.environ["ATLAS_TELEGRAM_WEBHOOK_ENABLED"] = "0"
            os.environ["ATLAS_TELEGRAM_BOT_TOKEN"] = ""
            os.environ["ATLAS_TELEGRAM_CHAT_ID"] = ""
            os.environ["ATLAS_CONSOLE_SIGNAL_PRINT_ENABLED"] = "0"
            from config import Config
            Config.refresh_from_env()
            from atlas_runtime import AtlasRuntime
            _runtime = AtlasRuntime()
            _runtime.start()
        return _runtime


def best_symbols(limit=5):
    from data_engine import exchange
    from universe_engine import select_symbols
    markets = exchange.load_markets()
    symbols, _ = select_symbols(
        markets=markets, suffix="/USDT:USDT", require_active=True,
        require_swap=False, max_symbols=0,
    )
    tickers = exchange.fetch_tickers(symbols)
    ranked = []
    for symbol in symbols:
        ticker = (tickers or {}).get(symbol) or {}
        try:
            volume = float(ticker.get("quoteVolume") or 0)
        except (TypeError, ValueError):
            volume = 0
        if volume > 0:
            ranked.append((volume, symbol))
    ranked.sort(reverse=True)
    return [symbol for _, symbol in ranked[:limit]]


def analyze_command(command):
    from utils.signal_card import build_signal_card
    normalized = command.strip().lower()
    if normalized in {"yardım", "yardim", "help", "?"}:
        return {"ok": True, "kind": "help", "message":
                "Coin sembolü yaz: BTC, ETH, BRC. 'İşlem ver' ilk 5 yüksek hacimli piyasada geçerli kurulum arar. Atlas emir göndermez."}
    runtime = get_runtime()
    with _analysis_lock:
        if normalized in {"işlem ver", "islem ver", "en iyi işlem", "en iyi islem", "best", "best trade"}:
            symbols = best_symbols(5)
            candidates = []
            errors = []
            for symbol in symbols:
                outcome = runtime.analyze_symbol(symbol, force_refresh=True)
                if not outcome.get("ok"):
                    errors.append(symbol)
                    continue
                card = build_signal_card(outcome["result"])
                if card.get("decision_action") != "EXECUTE" or card.get("direction") not in {"LONG", "SHORT"}:
                    continue
                try:
                    rr = float(card.get("rr") or 0)
                    quality = float(card.get("setup_quality") or 0)
                    confidence = float(card.get("confidence") or 0)
                except (TypeError, ValueError):
                    continue
                if card.get("entry") is None or card.get("stop_loss") is None or rr <= 0:
                    continue
                score = quality * 0.55 + confidence * 0.25 + min(rr, 5.0) * 4
                candidates.append((score, card))
            if not candidates:
                return {"ok": True, "kind": "none", "message":
                        "Şu an geçerli işlem yok. Taranan piyasalarda Atlas'ın koşullarını geçen kurulum bulunmadı; bekle."}
            candidates.sort(key=lambda item: item[0], reverse=True)
            score, card = candidates[0]
            return {"ok": True, "kind": "signal", "card": card,
                    "message": "En iyi bulunan kurulum (sıralama puanı kazanma olasılığı değildir).",
                    "scan_count": len(symbols), "valid_count": len(candidates), "score": round(score, 1)}
        outcome = runtime.analyze_symbol(command, force_refresh=True)
        if not outcome.get("ok"):
            return {"ok": False, "kind": "error",
                    "message": str(outcome.get("error", "Analiz başarısız"))}
        return {"ok": True, "kind": "signal", "card": build_signal_card(outcome["result"]),
                "elapsed_ms": outcome.get("elapsed_ms", 0)}


class Handler(BaseHTTPRequestHandler):
    server_version = "AtlasMobile/1.0"

    def log_message(self, fmt, *args):
        logging.getLogger("atlas.mobile").info("%s - %s", self.address_string(), fmt % args)

    def send_bytes(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
            "/sw.js": ("sw.js", "application/javascript; charset=utf-8"),
        }
        if path == "/api/health":
            self.send_bytes(200, "application/json; charset=utf-8",
                            json.dumps({"ok": True, "service": "Atlas Mobile"}).encode())
            return
        if path not in files:
            self.send_bytes(404, "text/plain; charset=utf-8", b"Not found")
            return
        name, content_type = files[path]
        try:
            body = (ROOT / "mobile" / name).read_bytes()
        except OSError:
            self.send_bytes(500, "text/plain; charset=utf-8", b"Mobile interface files missing")
            return
        self.send_bytes(200, content_type, body)

    def do_POST(self):
        if urlparse(self.path).path != "/api/command":
            self.send_bytes(404, "application/json", b'{"ok":false,"message":"Not found"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 2048:
                raise ValueError("Komut boş veya çok uzun.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            command = str(payload.get("command", "")).strip()
            if not command or len(command) > 40:
                raise ValueError("Geçerli bir coin veya komut gir.")
            result = analyze_command(command)
            body = json.dumps(result, ensure_ascii=False).encode("utf-8")
            self.send_bytes(200, "application/json; charset=utf-8", body)
        except Exception as exc:
            body = json.dumps({"ok": False, "kind": "error",
                               "message": f"{type(exc).__name__}: {exc}"},
                              ensure_ascii=False).encode("utf-8")
            self.send_bytes(400, "application/json; charset=utf-8", body)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Atlas Mobile hazır: http://127.0.0.1:{PORT}")
    print("Durdurmak için Ctrl+C. Yalnızca bu telefondan erişilebilir.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if _runtime is not None:
            _runtime.stop()


if __name__ == "__main__":
    main()
