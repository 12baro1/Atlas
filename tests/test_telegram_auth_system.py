import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram_auth import TelegramAuthService, TelegramRole, TelegramStatus
from telegram_auth_store import TelegramAuthStore
from telegram_engine import TelegramBot


def _new_store(tmp_path):
    db_path = tmp_path / "telegram_auth_test.db"
    return TelegramAuthStore(str(db_path))


def test_first_verified_user_becomes_admin(tmp_path):
    store = _new_store(tmp_path)
    service = TelegramAuthService(store=store, password="secret", admin_ids=[])

    reply = service.process_message(1001, "alice", "/start")
    assert "şifresini" in reply.lower()

    reply = service.process_message(1001, "alice", "wrong")
    assert "hatalı" in reply.lower()

    reply = service.process_message(1001, "alice", "secret")
    assert "başarılı" in reply.lower()

    user = store.get_user(1001)
    assert user["role"] == TelegramRole.ADMIN
    assert user["status"] == TelegramStatus.ACTIVE


def test_config_admin_id_gets_admin_role(tmp_path):
    store = _new_store(tmp_path)
    service = TelegramAuthService(store=store, password="secret", admin_ids=[7777])

    service.process_message(7777, "boss", "/start")
    service.process_message(7777, "boss", "secret")

    user = store.get_user(7777)
    assert user["role"] == TelegramRole.ADMIN


def test_admin_commands_and_ban_flow(tmp_path):
    store = _new_store(tmp_path)
    service = TelegramAuthService(store=store, password="secret", admin_ids=[])

    service.process_message(1, "admin", "/start")
    service.process_message(1, "admin", "secret")

    service.process_message(2, "user2", "/start")
    service.process_message(2, "user2", "secret")

    denied = service.process_message(2, "user2", "/admin_users")
    assert "sadece admin" in denied.lower()

    granted = service.process_message(1, "admin", "/admin_role 2 admin")
    assert "yetki güncellendi" in granted.lower()
    assert store.get_user(2)["role"] == TelegramRole.ADMIN

    banned = service.process_message(1, "admin", "/admin_ban 2")
    assert "banlandı" in banned.lower()
    assert store.get_user(2)["status"] == TelegramStatus.BANNED

    blocked = service.process_message(2, "user2", "/start")
    assert "ban" in blocked.lower()


def test_telegram_bot_loads_authorized_users_from_db(tmp_path):
    store = _new_store(tmp_path)
    store.upsert_user(901, "u1", TelegramRole.USER, TelegramStatus.ACTIVE)
    store.upsert_user(902, "u2", TelegramRole.ADMIN, TelegramStatus.ACTIVE)
    store.upsert_user(903, "u3", TelegramRole.USER, TelegramStatus.BANNED)

    bot = TelegramBot(auth_store=store)
    ids = bot.load_chat_ids()

    assert 901 in ids
    assert 902 in ids
    assert 903 not in ids
