"""Telegram buton tıklamalarını işleyen webhook modulu."""

import json
import logging
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import Config


LOGGER = logging.getLogger("atlas.telegram.webhook")


class TelegramWebhookHandler:
    """Telegram inline button callback'larını işler."""

    def __init__(self, trade_command_handler=None):
        Config.refresh_from_env()
        self.token = str(getattr(Config, "TELEGRAM_BOT_TOKEN", "")).strip()
        self.logger = logging.getLogger("atlas.telegram.webhook")
        self.trade_command_handler = trade_command_handler

    def handle_update(self, update_data):
        """
        Telegram'dan gelen update'i işler.
        
        Args:
            update_data: Telegram API'den gelen JSON data
            
        Returns:
            bool: İşlem başarılı mı?
        """
        try:
            if "callback_query" not in update_data:
                # Normal metin / media mesajı: işlem gerektirmez ama Telegram
                # 400 dönerse sonraki update'ler engellenir; bu yüzden ack ver.
                return True

            callback_query = update_data["callback_query"]
            chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
            message_id = callback_query.get("message", {}).get("message_id")
            callback_data = callback_query.get("data", "")
            user_id = callback_query.get("from", {}).get("id")

            if self.trade_command_handler is not None and hasattr(self.trade_command_handler, "handle_callback"):
                reply = self.trade_command_handler.handle_callback(callback_data)
                self._answer_callback_query(callback_query.get("id"), (reply or "İşlem alındı")[:180], show_alert=False)
                return True

            if not chat_id or not callback_data:
                LOGGER.warning("Geçersiz callback: chat_id=%s, callback_data=%s", chat_id, callback_data)
                return True

            parsed = self._parse_callback_data(callback_data)
            if parsed is None:
                LOGGER.warning("Geçersiz callback formatı: %s", callback_data)
                self._answer_callback_query(callback_query.get("id"), "❌ Geçersiz komut", show_alert=True)
                return True
            action, symbol = parsed

            # Kullanıcıyı doğrula (basit yetkilendirme)
            admin_chat_id = getattr(Config, "ADMIN_CHAT_ID", None)
            authorized_chat_ids = self._load_authorized_chat_ids()

            if str(chat_id) != str(admin_chat_id) and chat_id not in authorized_chat_ids:
                LOGGER.warning("Yetkisiz erişim: chat_id=%s, user_id=%s", chat_id, user_id)
                self._answer_callback_query(callback_query.get("id"), "❌ Yetkiniz yok", show_alert=True)
                return True

            # Aksiyonu işle
            result = self._process_action(action, symbol, chat_id, user_id)

            # Kullanıcıya geri bildirim gönder
            if result:
                self._answer_callback_query(callback_query.get("id"), result["message"])
                if result.get("edit_message"):
                    self._edit_message_text(chat_id, message_id, result["new_text"])
            else:
                self._answer_callback_query(callback_query.get("id"), "❌ İşlem başarısız", show_alert=True)

            return True

        except Exception as exc:
            LOGGER.exception("Webhook işlem hatası: %s", exc)
            return False

    @staticmethod
    def _parse_callback_data(callback_data):
        """telegram_engine.trade_feedback_keyboard ile uyumlu parse.

        Format: "trade_entered|BTC/USDT|LONG"
        Dönüş: (action, symbol) veya None.
        """
        parts = callback_data.split("|")
        if len(parts) < 2:
            return None
        raw_action = parts[0]
        symbol_index = 1
        if len(parts) >= 4 and str(parts[1]).startswith("ATL-"):
            symbol_index = 2
        symbol = parts[symbol_index].strip()
        if not symbol:
            return None
        if raw_action.startswith("trade_"):
            raw_action = raw_action[len("trade_"):]
        action_map = {
            "entered": "entered",
            "skipped": "skipped",
            "tp": "close",
            "sl": "close",
            "exit_early": "close",
        }
        action = action_map.get(raw_action, raw_action)
        return action, symbol

    def _process_action(self, action, symbol, chat_id, user_id):
        """
        Buton aksiyonunu işler.
        
        Args:
            action: entered, skipped, analyze, close, note
            symbol: Sembol (callback'ten gelen, örn. BTC/USDT)
            chat_id: Telegram chat ID
            user_id: Kullanıcı ID
            
        Returns:
            dict: {"message": str, "edit_message": bool, "new_text": str} veya None
        """
        action_handlers = {
            "entered": self._handle_entered,
            "skipped": self._handle_skipped,
            "analyze": self._handle_analyze,
            "close": self._handle_close,
            "note": self._handle_note,
        }

        handler = action_handlers.get(action)
        if not handler:
            LOGGER.warning("Bilinmeyen aksiyon: %s", action)
            return None

        return handler(symbol, chat_id, user_id)

    def _handle_entered(self, symbol, chat_id, user_id):
        """Kullanıcı işleme girdiğini belirtti."""
        LOGGER.info("Kullanıcı %s işleme GİRDİ: %s", user_id, symbol)
        
        # Trade journal'a kaydet (ileride genişletilebilir)
        self._log_trade_action(symbol, "ENTERED", user_id)
        
        return {
            "message": f"✅ {symbol} için 'Girdim' kaydınız alındı.",
            "edit_message": True,
            "new_text": f"📊 {symbol}\n✅ İŞLEME GİRİLDİ\nKullanıcı: {user_id}"
        }

    def _handle_skipped(self, symbol, chat_id, user_id):
        """Kullanıcı işleme girmediğini belirtti."""
        LOGGER.info("Kullanıcı %s işleme GİRMEDİ: %s", user_id, symbol)
        
        self._log_trade_action(symbol, "SKIPPED", user_id)
        
        return {
            "message": f"❌ {symbol} için 'Girmedim' kaydınız alındı.",
            "edit_message": False
        }

    def _handle_analyze(self, symbol, chat_id, user_id):
        """Kullanıcı ek analiz istedi."""
        LOGGER.info("Kullanıcı %s analiz istedi: %s", user_id, symbol)
        
        # Burada daha detaylı analiz yapılabilir
        analysis_text = f"📊 {symbol} Detaylı Analiz:\n\n"
        analysis_text += "• Trend: Kontrol ediliyor...\n"
        analysis_text += "• FVG: Hesaplanıyor...\n"
        analysis_text += "• Order Block: Belirleniyor...\n"
        analysis_text += "\n⏳ Detaylı analiz hazırlanıyor..."
        
        return {
            "message": f"📈 {symbol} için analiz isteğiniz alındı.",
            "edit_message": True,
            "new_text": analysis_text
        }

    def _handle_close(self, symbol, chat_id, user_id):
        """Kullanıcı pozisyonu kapattığını belirtti."""
        LOGGER.info("Kullanıcı %s pozisyonu KAPATTI: %s", user_id, symbol)
        
        self._log_trade_action(symbol, "CLOSED", user_id)
        
        return {
            "message": f"🚫 {symbol} için pozisyon kapatma kaydınız alındı.",
            "edit_message": True,
            "new_text": f"📊 {symbol}\n🚫 POZİSYON KAPATILDI\nKullanıcı: {user_id}"
        }

    def _handle_note(self, symbol, chat_id, user_id):
        """Kullanıcı not eklemek istedi."""
        LOGGER.info("Kullanıcı %s not eklemek istiyor: %s", user_id, symbol)
        
        return {
            "message": f"📝 {symbol} için not ekleme özelliği yakında aktif olacak.",
            "edit_message": False
        }

    def _log_trade_action(self, symbol, action, user_id):
        """Trade aksiyonunu logla."""
        log_entry = {
            "timestamp": self._get_timestamp(),
            "symbol": symbol,
            "action": action,
            "user_id": user_id
        }
        LOGGER.info("Trade Log: %s", json.dumps(log_entry))
        
        # İleride veritabanına kaydedilebilir

    def _get_timestamp(self):
        """Şu anki timestamp'i al."""
        from datetime import datetime
        return datetime.now().isoformat()

    def _load_authorized_chat_ids(self):
        """Yetkili chat ID'lerini yükle (telegram_auth_store.db + chat_ids.json)."""
        chat_ids = []

        try:
            from telegram_auth_store import TelegramAuthStore
            auth_db_file = getattr(Config, "TELEGRAM_AUTH_DB_FILE", "telegram_auth.db")
            store = TelegramAuthStore(auth_db_file)
            chat_ids.extend(store.list_authorized_chat_ids())
        except Exception:
            LOGGER.exception("Telegram auth db yuklenemedi")

        chat_ids_file = getattr(Config, "CHAT_IDS_FILE", "chat_ids.json")
        import os
        if os.path.exists(chat_ids_file):
            try:
                with open(chat_ids_file, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        chat_ids.extend([int(x) for x in data if str(x).isdigit()])
            except Exception:
                pass

        unique = []
        for chat_id in chat_ids:
            if chat_id not in unique:
                unique.append(chat_id)
        return unique

    def _answer_callback_query(self, callback_id, text, show_alert=False):
        """Callback query'ye cevap ver."""
        if not self.token:
            LOGGER.warning("Token yok, callback answer atlandı")
            return False

        url = f"https://api.telegram.org/bot{self.token}/answerCallbackQuery"
        payload = urlencode({
            "callback_query_id": callback_id,
            "text": text,
            "show_alert": "true" if show_alert else "false"
        }).encode("utf-8")
        
        request = Request(url, data=payload, method="POST")
        
        try:
            timeout = float(getattr(Config, "TELEGRAM_HTTP_TIMEOUT_SECONDS", 3))
            with urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", 0)
                return 200 <= status < 300
        except Exception as exc:
            LOGGER.exception("Callback answer hatası: %s", exc)
            return False

    def _edit_message_text(self, chat_id, message_id, new_text):
        """Mesajı düzenle."""
        if not self.token:
            return False

        url = f"https://api.telegram.org/bot{self.token}/editMessageText"
        payload = urlencode({
            "chat_id": chat_id,
            "message_id": message_id,
            "text": new_text
        }).encode("utf-8")
        
        request = Request(url, data=payload, method="POST")
        
        try:
            timeout = float(getattr(Config, "TELEGRAM_HTTP_TIMEOUT_SECONDS", 3))
            with urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", 0)
                return 200 <= status < 300
        except Exception as exc:
            LOGGER.exception("Mesaj düzenleme hatası: %s", exc)
            return False


# Webhook endpoint için basit handler
def webhook_handler(event, context):
    """
    AWS Lambda veya benzeri serverless fonksiyonlar için webhook handler.
    
    Args:
        event: HTTP request event
        context: Execution context
        
    Returns:
        dict: HTTP response
    """
    handler = TelegramWebhookHandler()
    
    try:
        body = json.loads(event.get("body", "{}"))
        success = handler.handle_update(body)
        
        return {
            "statusCode": 200 if success else 400,
            "body": json.dumps({"status": "ok" if success else "error"})
        }
    except Exception as exc:
        LOGGER.exception("Webhook handler hatası: %s", exc)
        return {
            "statusCode": 500,
            "body": json.dumps({"status": "error", "message": str(exc)})
        }
