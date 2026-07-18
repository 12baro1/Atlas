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

                    if text == "/start":

                        requests.post(
                            f"https://api.telegram.org/bot{self.token}/sendMessage",
                            data={
                                "chat_id": chat_id,
                                "text": "🔐 Şifreyi gönderiniz."
                            },
                            timeout=10
                        )

                    elif text == self.password:

                        added = self.add_user(chat_id)

                        if added:
                            reply = "✅ Yetkilendirildiniz. Bundan sonraki sinyal mesajları size de gönderilecek."
                        else:
                            reply = "✅ Zaten yetkilisiniz. Sinyal mesajları size gönderilecek."

                        requests.post(
                            f"https://api.telegram.org/bot{self.token}/sendMessage",
                            data={
                                "chat_id": chat_id,
                                "text": reply
                            },
                            timeout=10
                        )

                    else:

                        requests.post(
                            f"https://api.telegram.org/bot{self.token}/sendMessage",
                            data={
                                "chat_id": chat_id,
                                "text": "❌ Hatalı şifre."
                            },
                            timeout=10
                        )

            except Exception as e:

                print(e)
