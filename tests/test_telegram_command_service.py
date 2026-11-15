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
