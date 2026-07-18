"""
telegram_auth.py
Atlas Telegram Authentication & Authorization
"""

import base64
import hashlib
import hmac
import os

import requests

from config import Config
from telegram_auth_store import TelegramAuthStore


class TelegramRole:
    ADMIN = "ADMIN"
    USER = "USER"


class TelegramStatus:
    ACTIVE = "ACTIVE"
    BANNED = "BANNED"


class TelegramAuthService:
    """Telegram kullanıcı doğrulama ve RBAC akışını yönetir."""

    SESSION_AWAIT_PASSWORD = "AWAIT_PASSWORD"

    def __init__(self, store, password, admin_ids=None, password_hash=""):
        self.store = store
        self.password = password
        self.password_hash = password_hash
        self.admin_ids = {int(item) for item in (admin_ids or [])}

    def process_message(self, chat_id, username, text):
        """Mesajı işler ve uygun yanıt metnini döndürür."""
        user = self.store.get_user(chat_id)
        clean_text = (text or "").strip()

        if clean_text == "/start":
            return self._handle_start(chat_id, username, user)

        if user and user["status"] == TelegramStatus.BANNED:
            return "🚫 Hesabınız banlandı. Erişim engellendi."

        session_state = self.store.get_session_state(chat_id)
        if session_state == self.SESSION_AWAIT_PASSWORD:
            return self._handle_password(chat_id, username, clean_text)

        if not user or user["status"] != TelegramStatus.ACTIVE:
            return "🔐 Önce /start komutunu gönderin ve doğrulama yapın."

        if clean_text.startswith("/admin"):
            return self._handle_admin_command(chat_id, clean_text)

        if clean_text.startswith("/"):
            return "✅ Yetkilendirildiniz. Atlas komutlarını kullanabilirsiniz."

        return None

    def is_authorized(self, chat_id):
        user = self.store.get_user(chat_id)
        return bool(user and user["status"] == TelegramStatus.ACTIVE)

    def _handle_start(self, chat_id, username, user):
        if user and user["status"] == TelegramStatus.BANNED:
            return "🚫 Hesabınız banlandı."

        if user and user["status"] == TelegramStatus.ACTIVE:
            role = user["role"]
            return f"✅ Hoş geldiniz. Rolünüz: {role}"

        self.store.set_session_state(chat_id, self.SESSION_AWAIT_PASSWORD)
        return "🔐 Erişim şifresini gönderin."

    def _handle_password(self, chat_id, username, candidate):
        if not self._verify_password(candidate):
            return "❌ Hatalı şifre. Tekrar deneyin."

        role = self._initial_role_for(chat_id)
        self.store.upsert_user(
            telegram_id=chat_id,
            username=username,
            role=role,
            status=TelegramStatus.ACTIVE,
        )
        self.store.clear_session(chat_id)

        return f"✅ Doğrulama başarılı. Rolünüz: {role}"

    def _initial_role_for(self, chat_id):
        if int(chat_id) in self.admin_ids:
            return TelegramRole.ADMIN

        if self.store.count_admins() == 0:
            return TelegramRole.ADMIN

        return TelegramRole.USER

    def _verify_password(self, candidate):
        if self.password_hash:
            return self._verify_password_hash(candidate, self.password_hash)

        return hmac.compare_digest(str(candidate), str(self.password))

    def _verify_password_hash(self, candidate, encoded_hash):
        """pbkdf2_sha256$iterations$salt$hash formatını doğrular."""
        try:
            algorithm, raw_iterations, salt, expected = encoded_hash.split("$", maxsplit=3)
            if algorithm != "pbkdf2_sha256":
                return False

            iterations = int(raw_iterations)
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                candidate.encode("utf-8"),
                salt.encode("utf-8"),
                iterations,
            )
            computed = base64.b64encode(digest).decode("utf-8")
            return hmac.compare_digest(computed, expected)
        except Exception:
            return False

    def _handle_admin_command(self, chat_id, text):
        actor = self.store.get_user(chat_id)
        if not actor or actor["role"] != TelegramRole.ADMIN or actor["status"] != TelegramStatus.ACTIVE:
            return "⛔ Bu komut sadece admin kullanıcılara açıktır."

        parts = text.split()
        command = parts[0].lower()

        if command == "/admin_users":
            return self._command_list_users()

        if len(parts) < 2:
            return "ℹ Kullanım: /admin_add <id> [admin|user] | /admin_del <id> | /admin_ban <id> | /admin_role <id> <admin|user>"

        if command == "/admin_add":
            role = TelegramRole.USER
            if len(parts) >= 3 and parts[2].lower() == "admin":
                role = TelegramRole.ADMIN
            return self._command_add(parts[1], role)

        if command == "/admin_del":
            return self._command_delete(parts[1])

        if command == "/admin_ban":
            return self._command_ban(parts[1])

        if command == "/admin_role":
            if len(parts) < 3:
                return "ℹ Kullanım: /admin_role <id> <admin|user>"
            role = TelegramRole.ADMIN if parts[2].lower() == "admin" else TelegramRole.USER
            return self._command_role(parts[1], role)

        return "ℹ Bilinmeyen admin komutu."

    def _command_list_users(self):
        users = self.store.list_users()
        if not users:
            return "📭 Kayıtlı kullanıcı yok."

        lines = ["👥 Kullanıcılar:"]
        for user in users:
            uname = user["username"] or "-"
            lines.append(f"- {user['telegram_id']} | {uname} | {user['role']} | {user['status']}")

        return "\n".join(lines)

    def _command_add(self, raw_chat_id, role):
        target = self._parse_chat_id(raw_chat_id)
        if target is None:
            return "❌ Geçersiz Telegram ID."

        existing = self.store.get_user(target)
        username = existing["username"] if existing else None
        self.store.upsert_user(
            telegram_id=target,
            username=username,
            role=role,
            status=TelegramStatus.ACTIVE,
        )
        return f"✅ Kullanıcı eklendi/güncellendi: {target} ({role})"

    def _command_delete(self, raw_chat_id):
        target = self._parse_chat_id(raw_chat_id)
        if target is None:
            return "❌ Geçersiz Telegram ID."

        if self.store.delete_user(target):
            return f"🗑 Kullanıcı silindi: {target}"

        return "ℹ Kullanıcı bulunamadı."

    def _command_ban(self, raw_chat_id):
        target = self._parse_chat_id(raw_chat_id)
        if target is None:
            return "❌ Geçersiz Telegram ID."

        if self.store.update_status(target, TelegramStatus.BANNED):
            return f"🚫 Kullanıcı banlandı: {target}"

        return "ℹ Kullanıcı bulunamadı."

    def _command_role(self, raw_chat_id, role):
        target = self._parse_chat_id(raw_chat_id)
        if target is None:
            return "❌ Geçersiz Telegram ID."

        if self.store.update_role(target, role):
            return f"🛡 Yetki güncellendi: {target} -> {role}"

        return "ℹ Kullanıcı bulunamadı."

    def _parse_chat_id(self, raw_chat_id):
        try:
            return int(raw_chat_id)
        except Exception:
            return None


class TelegramAuth:
    """Telegram polling akışında auth komutlarını çalıştırır."""

    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN
        self.store = TelegramAuthStore(Config.TELEGRAM_AUTH_DB_FILE)
        self.service = TelegramAuthService(
            store=self.store,
            password=Config.BOT_PASSWORD,
            password_hash=Config.BOT_PASSWORD_HASH,
            admin_ids=Config.TELEGRAM_ADMIN_IDS,
        )

    def get_updates(self, offset=None):
        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        params = {}

        if offset is not None:
            params["offset"] = offset

        response = requests.get(url, params=params, timeout=10)
        return response.json()

    def send_message(self, chat_id, text):
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": text,
            },
            timeout=10,
        )

    def run(self):
        offset = None
        print("Telegram Auth Service Started")

        while True:
            try:
                updates = self.get_updates(offset)
                if not updates.get("ok"):
                    continue

                for update in updates.get("result", []):
                    offset = update["update_id"] + 1
                    message = update.get("message")
                    if not message:
                        continue

                    text = message.get("text")
                    if text is None:
                        continue

                    chat = message.get("chat", {})
                    sender = message.get("from", {})
                    chat_id = chat.get("id")
                    username = sender.get("username") or sender.get("first_name")
                    if chat_id is None:
                        continue

                    reply = self.service.process_message(chat_id, username, text)
                    if reply:
                        self.send_message(chat_id, reply)

            except Exception as error:
                print("Telegram Auth Error:", error)


def hash_password(password, iterations=200_000):
    """Production için PBKDF2 tabanlı şifre hash çıktısı üretir."""
    salt = base64.b64encode(os.urandom(16)).decode("utf-8")
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    encoded = base64.b64encode(digest).decode("utf-8")
    return f"pbkdf2_sha256${iterations}${salt}${encoded}"
