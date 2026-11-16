from telegram_command_service import (
    TelegramCommandService,
    is_recognized_command,
    normalize_command,
    split_message,
)


def test_normalize_plain_and_addressed_commands():
    assert normalize_command("  BTC   ") == "BTC"
    assert normalize_command("/help@Oakmontincbot") == "help"


def test_recognizes_terminal_commands():
    for command in (
        "BTC",
        "ETH",
        "en iyi 5 işlem",
        "50 analiz et",
        "tüm piyasayı tara",
        "likidite BTC",
        "performans",
        "öğrenme",
        "yardım",
    ):
        assert is_recognized_command(command), command


def test_ignores_unrecognized_group_chat():
    assert not is_recognized_command("Günaydın herkes")
    assert not is_recognized_command("fiyat kaç olur?")


def test_split_message_respects_telegram_limit():
    chunks = split_message(("satır\n" * 1200), limit=100)
    assert len(chunks) > 1
    assert all(len(chunk) <= 100 for chunk in chunks)


def test_service_requires_explicit_group_target():
    service = TelegramCommandService(object(), "token", "-100123")
    assert service.enabled
    service_without_chat = TelegramCommandService(object(), "token", "")
    assert not service_without_chat.enabled



def test_start_clears_stale_webhook_before_polling(monkeypatch):
    service = TelegramCommandService(object(), "token", "-100123")
    calls = []

    class FakeThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            calls.append(("thread_started", self.kwargs["name"]))

        def is_alive(self):
            return False

    def fake_api(method, payload, timeout=25):
        calls.append((method, payload, timeout))
        return True

    monkeypatch.setattr(service, "_api", fake_api)
    monkeypatch.setattr("telegram_command_service.threading.Thread", FakeThread)

    assert service.start() is True
    assert calls[0] == ("deleteWebhook", {"drop_pending_updates": True}, 10)
    assert calls[1] == ("thread_started", "atlas-telegram-commands")
