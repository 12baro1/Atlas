"""
telegram_auth.py
Atlas Telegram Authentication
"""

import json
import os
import requests

from config import Config


class TelegramAuth:

    def __init__(self):

        self.token = Config.TELEGRAM_BOT_TOKEN
        self.password = Config.BOT_PASSWORD
        self.file = Config.CHAT_IDS_FILE
        self.admin_chat_id = Config.ADMIN_CHAT_ID

        if not os.path.exists(self.file):
            with open(self.file, "w") as f:
                json.dump([], f)

    def load_users(self):

        with open(self.file, "r") as f:
            return json.load(f)

    def save_users(self, users):

        with open(self.file, "w") as f:
            json.dump(users, f, indent=4)

    def add_user(self, chat_id):

        users = self.load_users()

        if chat_id not in users:
            users.append(chat_id)
            self.save_users(users)
            return True

        return False

    def is_admin(self, chat_id):

        return str(chat_id) == str(self.admin_chat_id)

    def send_message(self, chat_id, text, reply_markup=None):

        data = {
            "chat_id": chat_id,
            "text": text
        }

        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)

        requests.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            data=data,
            timeout=10
        )

    def send_admin_menu(self, chat_id):

        self.send_message(
            chat_id,
            "🛠 Admin Menüsü\nBir işlem seçiniz.",
            {
                "keyboard": [
                    ["👥 Kullanıcıları Listele", "🔢 Kullanıcı Sayısı"],
                    ["📣 Test Mesajı", "❌ Menüyü Kapat"]
                ],
                "resize_keyboard": True,
                "one_time_keyboard": False
            }
        )

    def handle_admin_command(self, chat_id, text):

        if not self.is_admin(chat_id):
            return False

        if text == "/admin":
            self.send_admin_menu(chat_id)
            return True

        if text == "👥 Kullanıcıları Listele":
            users = self.load_users()

            if users:
                user_lines = [f"- {user}" for user in users]
                message = "👥 Yetkili Kullanıcılar:\n" + "\n".join(user_lines)
            else:
                message = "👥 Kayıtlı yetkili kullanıcı yok."

            self.send_message(chat_id, message)
            return True

        if text == "🔢 Kullanıcı Sayısı":
            users = self.load_users()
            self.send_message(chat_id, f"🔢 Yetkili kullanıcı sayısı: {len(users)}")
            return True

        if text == "📣 Test Mesajı":
            self.send_message(chat_id, "✅ Admin test mesajı başarılı.")
            return True

        if text == "❌ Menüyü Kapat":
            self.send_message(
                chat_id,
                "✅ Admin menüsü kapatıldı.",
                {"remove_keyboard": True}
            )
            return True

        return False

    def get_updates(self, offset=None):

        url = f"https://api.telegram.org/bot{self.token}/getUpdates"

        params = {}

        if offset:
            params["offset"] = offset

        r = requests.get(url, params=params, timeout=10)

        return r.json()

    def run(self):

        offset = None

        print("Telegram Auth Started")

        while True:

            try:

                data = self.get_updates(offset)

                if not data["ok"]:
                    continue

                for update in data["result"]:

                    offset = update["update_id"] + 1

                    if "message" not in update:
                        continue

                    message = update["message"]

                    if "text" not in message:
                        continue

                    text = message["text"].strip()
                    chat_id = message["chat"]["id"]

                    if self.handle_admin_command(chat_id, text):
                        continue

                    if text == "/start":
                        start_message = "🔐 Şifreyi gönderiniz."

                        if self.is_admin(chat_id):
                            start_message += "\n\nAdmin menüsü için /admin yazınız."

                        self.send_message(chat_id, start_message)

                    elif text == self.password:

                        added = self.add_user(chat_id)

                        if added:
                            reply = "✅ Yetkilendirildiniz. Bundan sonraki sinyal mesajları size de gönderilecek."
                        else:
                            reply = "✅ Zaten yetkilisiniz. Sinyal mesajları size gönderilecek."

                        if self.is_admin(chat_id):
                            reply += "\n\nAdmin menüsü için /admin yazınız."

                        self.send_message(chat_id, reply)

                    else:
                        self.send_message(chat_id, "❌ Hatalı şifre.")

            except Exception as e:

                print(e)
