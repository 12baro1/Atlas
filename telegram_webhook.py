"""Telegram buton tıklamalarını işleyen webhook modulu."""

import json
import logging
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import Config


LOGGER = logging.getLogger("atlas.telegram.webhook")


class TelegramWebhookHandler:
    """Telegram inline button callback'larını işler."""

    def __init__(self):
        Config.refresh_from_env()
        self.token = str(getattr(Config, "TELEGRAM_BOT_TOKEN", "")).strip()
        self.logger = logging.getLogger("atlas.telegram.webhook")

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
                return False

            callback_query = update_data["callback_query"]
            chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
            message_id = callback_query.get("message", {}).get("message_id")
            callback_data = callback_query.get("data", "")
            user_id = callback_query.get("from", {}).get("id")

            if not chat_id or not callback_data:
                LOGGER.warning("Geçersiz callback: chat_id=%s, callback_data=%s", chat_id, callback_data)
                return False

            # Callback verisini parse et
            parts = callback_data.split("_", 1)
            if len(parts) != 2:
                LOGGER.warning("Geçersiz callback formatı: %s", callback_data)
                return False

            action, signal_id = parts

            # Kullanıcıyı doğrula (basit yetkilendirme)
            admin_chat_id = getattr(Config, "ADMIN_CHAT_ID", None)
            authorized_chat_ids = self._load_authorized_chat_ids()
            
            if str(chat_id) != str(admin_chat_id) and chat_id not in authorized_chat_ids:
                LOGGER.warning("Yetkisiz erişim: chat_id=%s, user_id=%s", chat_id, user_id)
                self._answer_callback_query(callback_query.get("id"), "❌ Yetkiniz yok", show_alert=True)
                return False

            # Aksiyonu işle
            result = self._process_action(action, signal_id, chat_id, user_id)

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

    def _process_action(self, action, signal_id, chat_id, user_id):
        """
        Buton aksiyonunu işler.
        
        Args:
            action: entered, skipped, analyze, close, note
            signal_id: Sembol veya sinyal ID'si
            chat_id: Telegram chat ID
            user_id: Kullanıcı ID
            
        Returns:
            dict: {"message": str, "edit_message": bool, "new_text": str} veya None
        """
        symbol = signal_id.replace("_", "/")  # BTC/USDT formatına çevir

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
        """Yetkili chat ID'lerini yükle."""
        # Basit implementasyon - Config'den alınabilir
        auth_db_file = getattr(Config, "TELEGRAM_AUTH_DB_FILE", "telegram_auth.db")
        chat_ids_file = getattr(Config, "CHAT_IDS_FILE", "chat_ids.json")
        
        chat_ids = []
        
        # JSON dosyasından yükle
        import os
        if os.path.exists(chat_ids_file):
            try:
                with open(chat_ids_file, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        chat_ids.extend([int(x) for x in data if str(x).isdigit()])
            except Exception:
                pass
        
        return chat_ids

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
